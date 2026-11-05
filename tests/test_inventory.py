import threading
import unittest
from datetime import timedelta

from django.db import connection, connections
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from apps.cart.models import Cart, CartItem
from apps.core.models import AuditLog
from apps.inventory import services as inv
from apps.inventory.models import InventoryMovement, InventoryReservation
from apps.orders.models import Order, OrderStatus
from apps.orders.services import CheckoutError, create_order_from_cart, mark_paid

from . import factories as f


class StockMovementTests(TestCase):
    def test_entry_exit_adjust_with_history_and_audit(self):
        v = f.variant(stock=0)
        admin = f.staff()
        inv.record_movement(v.pk, InventoryMovement.Kind.ENTRY, 10, user=admin, reason="NF 123")
        inv.record_movement(v.pk, InventoryMovement.Kind.EXIT, 3, user=admin, reason="brinde")
        inv.set_stock(v.pk, 5, user=admin)
        v.refresh_from_db()
        self.assertEqual(v.stock, 5)
        kinds = list(InventoryMovement.objects.filter(variant=v).order_by("id").values_list("kind", "quantity", "stock_after"))
        self.assertEqual(kinds, [("entry", 10, 10), ("exit", -3, 7), ("adjustment", -2, 5)])
        self.assertEqual(AuditLog.objects.filter(action=AuditLog.Action.STOCK_MOVEMENT).count(), 3)

    def test_cannot_go_negative(self):
        v = f.variant(stock=2)
        with self.assertRaises(inv.InventoryError):
            inv.record_movement(v.pk, InventoryMovement.Kind.EXIT, 3)
        v.refresh_from_db()
        self.assertEqual(v.stock, 2)

    def test_cannot_reduce_below_reserved(self):
        v = f.variant(stock=5)
        order = Order.objects.create(email="a@a.com", customer_name="A", phone="1", ship_recipient="A", ship_cep="1",
                                     ship_street="R", ship_number="1", ship_neighborhood="B", ship_city="C", ship_state="SP",
                                     shipping_name="X", subtotal=1, total=1)
        inv.reserve_for_order(order, {v.pk: 4})
        with self.assertRaises(inv.InventoryError):
            inv.record_movement(v.pk, InventoryMovement.Kind.LOSS, 2)

    def test_database_constraint_blocks_negative_stock(self):
        from django.db import IntegrityError, transaction

        v = f.variant(stock=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            type(v).objects.filter(pk=v.pk).update(stock=-1)


class ReservationFlowTests(TestCase):
    def setUp(self):
        self.method = f.shipping_fixed()

    def _order(self, v, qty=1, email="c@exemplo.com"):
        cart = f.cart_with(v, qty)
        return create_order_from_cart(cart, f.checkout_data(shipping_code=f"m{self.method.pk}", email=email))

    def test_order_reserves_and_payment_consumes(self):
        v = f.variant(stock=5)
        order = self._order(v, 2)
        v.refresh_from_db()
        self.assertEqual((v.stock, v.reserved, v.available), (5, 2, 3))
        mark_paid(order)
        v.refresh_from_db()
        self.assertEqual((v.stock, v.reserved), (3, 0))
        self.assertEqual(InventoryReservation.objects.get(order=order).status, "consumed")
        self.assertTrue(InventoryMovement.objects.filter(order=order, kind="sale", quantity=-2).exists())

    def test_cannot_oversell_sequentially(self):
        v = f.variant(stock=1)
        self._order(v, 1, email="a@exemplo.com")
        with self.assertRaises(CheckoutError):
            self._order(v, 1, email="b@exemplo.com")
        v.refresh_from_db()
        self.assertEqual((v.stock, v.reserved), (1, 1))

    def test_expired_reservation_released_and_order_cancelled(self):
        v = f.variant(stock=2)
        order = self._order(v, 2)
        InventoryReservation.objects.filter(order=order).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(inv.release_expired_reservations(), 1)
        v.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(v.reserved, 0)
        self.assertEqual(order.status, OrderStatus.CANCELLED)

    def test_late_payment_after_expiry_takes_stock_and_flags(self):
        v = f.variant(stock=2)
        order = self._order(v, 1)
        InventoryReservation.objects.filter(order=order).update(expires_at=timezone.now() - timedelta(minutes=1))
        inv.release_expired_reservations()
        mark_paid(order)
        order.refresh_from_db()
        v.refresh_from_db()
        self.assertTrue(order.needs_attention)
        self.assertEqual(v.stock, 1)
        self.assertIn(order.status, (OrderStatus.PAID, OrderStatus.CUSTOMIZING))

    def test_cancel_paid_order_restocks(self):
        from apps.orders.services import cancel_order

        v = f.variant(stock=3)
        order = self._order(v, 2)
        mark_paid(order)
        cancel_order(order, reason="cliente desistiu", restock=True)
        v.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(v.stock, 3)
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertTrue(order.needs_attention)  # reembolso pendente no gateway


@unittest.skipUnless(connection.vendor == "postgresql",
                     "Teste de concorrência real requer PostgreSQL (SELECT ... FOR UPDATE). Rode com DATABASE_URL apontando para Postgres.")
class ConcurrencyTests(TransactionTestCase):
    def test_parallel_checkouts_never_oversell(self):
        method = f.shipping_fixed()
        v = f.variant(stock=3)
        carts = []
        for i in range(8):
            c = Cart.objects.create(session_key=f"conc{i}")
            CartItem.objects.create(cart=c, variant=v, quantity=1)
            carts.append(c)
        results, barrier = [], threading.Barrier(len(carts))

        def worker(cart, i):
            try:
                barrier.wait()
                create_order_from_cart(cart, f.checkout_data(shipping_code=f"m{method.pk}", email=f"c{i}@exemplo.com"))
                results.append("ok")
            except CheckoutError:
                results.append("sem estoque")
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(c, i)) for i, c in enumerate(carts)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        v.refresh_from_db()
        self.assertEqual(results.count("ok"), 3)
        self.assertEqual(v.reserved, 3)
        self.assertLessEqual(v.reserved, v.stock)
