import hashlib
import hmac
import json
from decimal import Decimal

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.orders.models import Order, OrderStatus, PaymentStatus
from apps.orders.services import CheckoutError, change_status, create_order_from_cart
from apps.payments.gateway import set_gateway_for_tests, verify_webhook_signature
from apps.payments.models import Payment, PaymentEvent
from apps.promotions.models import Coupon

from . import factories as f

SECRET = "segredo-de-teste"


def signed_headers(data_id, request_id="req-1", ts="1730000000", secret=SECRET):
    manifest = f"id:{data_id};request-id:{request_id};ts:{ts};"
    sig = hmac.new(secret.encode(), manifest.encode(), hashlib.sha256).hexdigest()
    return {"HTTP_X_SIGNATURE": f"ts={ts},v1={sig}", "HTTP_X_REQUEST_ID": request_id}


class OrderCreationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.method = f.shipping_fixed(price="20.00")

    def test_totals_snapshot_and_cart_cleared(self):
        v = f.variant(f.product(price="100.00", cost="40.00"), stock=5)
        cart = f.cart_with(v, 2)
        c = Coupon.objects.create(code="DEZ", kind="percent", value=10)
        cart.coupon = c
        cart.save()
        order = create_order_from_cart(cart, f.checkout_data(shipping_code=f"m{self.method.pk}"))
        self.assertEqual(order.subtotal, Decimal("200.00"))
        self.assertEqual(order.coupon_discount, Decimal("20.00"))
        self.assertEqual(order.shipping_cost, Decimal("20.00"))
        self.assertEqual(order.total, Decimal("200.00"))
        item = order.items.get()
        self.assertEqual((item.unit_price, item.unit_cost, item.sku), (Decimal("100.00"), Decimal("40.00"), v.sku))
        self.assertFalse(cart.items.exists())
        self.assertEqual(order.status, OrderStatus.AWAITING_PAYMENT)
        # Histórico preservado mesmo se o produto mudar depois.
        v.product.name = "Nome novo"
        v.product.price = Decimal("999")
        v.product.save()
        item.refresh_from_db()
        self.assertNotEqual(item.product_name, "Nome novo")
        self.assertEqual(item.unit_price, Decimal("100.00"))

    def test_invalid_shipping_code_rejected(self):
        v = f.variant(stock=5)
        with self.assertRaises(CheckoutError):
            create_order_from_cart(f.cart_with(v), f.checkout_data(shipping_code="m999999"))

    def test_shipping_region_restriction(self):
        restricted = f.shipping_fixed(states="RJ")
        v = f.variant(stock=5)
        with self.assertRaises(CheckoutError):  # CEP de SP não atende método só-RJ
            create_order_from_cart(f.cart_with(v), f.checkout_data(shipping_code=f"m{restricted.pk}"))

    def test_free_shipping_threshold(self):
        free = f.shipping_fixed(price="30.00", free_above=Decimal("150"))
        v = f.variant(f.product(price="160.00"), stock=5)
        order = create_order_from_cart(f.cart_with(v), f.checkout_data(shipping_code=f"m{free.pk}"))
        self.assertEqual(order.shipping_cost, Decimal("0.00"))

    def test_checkout_view_guest_flow_without_gateway_in_dev(self):
        v = f.variant(stock=5)
        self.client.post(reverse("cart:add"), {"variant_id": v.pk, "quantity": 1})
        data = {"email": "visitante@exemplo.com", "full_name": "Visitante Teste", "phone": "11988887777", "cpf": "",
                "cep": "05860-000", "street": "Rua A", "number": "10", "neighborhood": "Capão", "city": "São Paulo",
                "state": "SP", "shipping_code": f"m{self.method.pk}", "accept_terms": "on"}
        with override_settings(MERCADOPAGO_ACCESS_TOKEN="", ALLOW_ORDERS_WITHOUT_GATEWAY=True),                 self.captureOnCommitCallbacks(execute=True):
            resp = self.client.post(reverse("cart:checkout"), data)
        order = Order.objects.get()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(order.payment_status, PaymentStatus.PENDING, "nunca marcar como pago sem gateway")
        self.assertEqual(len(mail.outbox), 1)

    def test_checkout_blocked_when_gateway_not_configured_in_production_mode(self):
        v = f.variant(stock=5)
        self.client.post(reverse("cart:add"), {"variant_id": v.pk, "quantity": 1})
        with override_settings(MERCADOPAGO_ACCESS_TOKEN="", ALLOW_ORDERS_WITHOUT_GATEWAY=False):
            resp = self.client.post(reverse("cart:checkout"), {"email": "x@exemplo.com"})
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, "Pagamento online ainda não ativado")
        self.assertFalse(Order.objects.exists())

    def test_invalid_cpf_rejected(self):
        v = f.variant(stock=5)
        self.client.post(reverse("cart:add"), {"variant_id": v.pk, "quantity": 1})
        with override_settings(ALLOW_ORDERS_WITHOUT_GATEWAY=True):
            resp = self.client.post(reverse("cart:checkout"), {"cpf": "111.111.111-11", "email": "x@exemplo.com"})
        self.assertIn("cpf", resp.context["form"].errors)

    def test_status_transitions_validated(self):
        v = f.variant(stock=5)
        order = create_order_from_cart(f.cart_with(v), f.checkout_data(shipping_code=f"m{self.method.pk}"))
        with self.assertRaises(CheckoutError):
            change_status(order, OrderStatus.SHIPPED)  # não pago não pode ser enviado


class OrderPrivacyTests(TestCase):
    def setUp(self):
        self.method = f.shipping_fixed()

    def test_user_cannot_see_other_users_order(self):
        owner, other = f.user(), f.user()
        order = create_order_from_cart(f.cart_with(f.variant(stock=3), user_obj=owner),
                                       f.checkout_data(shipping_code=f"m{self.method.pk}"), user=owner)
        self.client.force_login(other)
        self.assertEqual(self.client.get(order.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.post(reverse("orders:pay", args=[order.public_id])).status_code, 404)
        self.client.force_login(owner)
        self.assertEqual(self.client.get(order.get_absolute_url()).status_code, 200)

    def test_guest_order_requires_signed_token(self):
        order = create_order_from_cart(f.cart_with(f.variant(stock=3)), f.checkout_data(shipping_code=f"m{self.method.pk}"))
        self.assertEqual(self.client.get(order.get_absolute_url()).status_code, 404)
        self.assertEqual(self.client.get(order.get_absolute_url() + "?t=forjado").status_code, 404)
        self.assertEqual(self.client.get(order.get_absolute_url() + f"?t={order.access_token()}").status_code, 200)

    def test_order_list_only_own(self):
        a, b = f.user(), f.user()
        create_order_from_cart(f.cart_with(f.variant(stock=3), user_obj=b), f.checkout_data(shipping_code=f"m{self.method.pk}"), user=b)
        self.client.force_login(a)
        self.assertEqual(len(self.client.get(reverse("accounts:orders")).context["orders"]), 0)


@override_settings(MERCADOPAGO_ACCESS_TOKEN="TEST-token", MERCADOPAGO_WEBHOOK_SECRET=SECRET, MERCADOPAGO_ENVIRONMENT="sandbox")
class PaymentWebhookTests(TestCase):
    def setUp(self):
        cache.clear()
        self.gateway = f.FakeGateway()
        set_gateway_for_tests(self.gateway)
        self.method = f.shipping_fixed()
        self.variant = f.variant(stock=5)
        self.order = create_order_from_cart(f.cart_with(self.variant, 2), f.checkout_data(shipping_code=f"m{self.method.pk}"))

    def tearDown(self):
        set_gateway_for_tests(None)

    def post_webhook(self, payment_id, headers=None, request_id="req-1"):
        url = reverse("payments:webhook") + f"?data.id={payment_id}&type=payment"
        body = json.dumps({"action": "payment.updated", "type": "payment", "data": {"id": str(payment_id)}})
        return self.client.post(url, body, content_type="application/json",
                                **(headers if headers is not None else signed_headers(payment_id, request_id)))

    def test_signature_verification(self):
        h = signed_headers("123")
        self.assertTrue(verify_webhook_signature(secret=SECRET, x_signature=h["HTTP_X_SIGNATURE"], x_request_id="req-1", data_id="123"))
        self.assertFalse(verify_webhook_signature(secret="outro", x_signature=h["HTTP_X_SIGNATURE"], x_request_id="req-1", data_id="123"))
        self.assertFalse(verify_webhook_signature(secret=SECRET, x_signature=h["HTTP_X_SIGNATURE"], x_request_id="req-2", data_id="123"))

    def test_invalid_signature_rejected_and_order_untouched(self):
        self.gateway.add_payment(self.order, "555")
        resp = self.post_webhook("555", headers={"HTTP_X_SIGNATURE": "ts=1,v1=deadbeef", "HTTP_X_REQUEST_ID": "x"})
        self.assertEqual(resp.status_code, 401)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.AWAITING_PAYMENT)

    def test_approved_payment_marks_paid_and_consumes_stock(self):
        self.gateway.add_payment(self.order, "777")
        resp = self.post_webhook("777")
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.variant.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PAID)
        self.assertEqual(self.order.payment_status, PaymentStatus.APPROVED)
        self.assertEqual((self.variant.stock, self.variant.reserved), (3, 0))
        payment = Payment.objects.get(external_id="777")
        self.assertNotIn("card", payment.raw, "dados de cartão não são armazenados")
        self.variant.product.refresh_from_db()
        self.assertEqual(self.variant.product.sold_count, 2)

    def test_webhook_idempotent(self):
        self.gateway.add_payment(self.order, "888")
        self.post_webhook("888", request_id="same")
        resp = self.post_webhook("888", request_id="same")
        self.assertEqual(resp.json()["status"], "already processed")
        self.post_webhook("888", request_id="retry-diferente")  # reprocessamento também não duplica
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock, 3)
        self.assertEqual(Payment.objects.filter(external_id="888").count(), 1)
        self.assertEqual(PaymentEvent.objects.get(idempotency_key__contains="same").attempts, 2)
        self.assertEqual(self.order.history.filter(to_status=OrderStatus.PAID).count(), 1)

    def test_amount_mismatch_not_approved(self):
        self.gateway.add_payment(self.order, "999", amount=Decimal("1.00"))
        self.post_webhook("999")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.AWAITING_PAYMENT)
        self.assertTrue(self.order.needs_attention)

    @override_settings(MERCADOPAGO_ENVIRONMENT="production")
    def test_test_payment_in_production_not_approved(self):
        self.gateway.add_payment(self.order, "1001", live_mode=False)
        self.post_webhook("1001")
        self.order.refresh_from_db()
        self.assertNotEqual(self.order.payment_status, PaymentStatus.APPROVED)

    def test_rejected_then_approved(self):
        self.gateway.add_payment(self.order, "2001", status="rejected")
        self.post_webhook("2001")
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, PaymentStatus.REJECTED)
        self.gateway.add_payment(self.order, "2002", status="approved")
        self.post_webhook("2002")
        self.post_webhook("2001", request_id="late-reject")  # notificação atrasada não rebaixa
        self.order.refresh_from_db()
        self.assertEqual(self.order.payment_status, PaymentStatus.APPROVED)

    def test_refund_marks_refunded(self):
        self.gateway.add_payment(self.order, "3001")
        self.post_webhook("3001")
        self.gateway.add_payment(self.order, "3001", status="refunded")
        self.post_webhook("3001", request_id="refund")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.REFUNDED)
        self.assertTrue(self.order.needs_attention)

    def test_return_url_params_alone_never_mark_paid(self):
        # Pagamento não existe no gateway: o navegador "diz" que foi aprovado, mas nada muda.
        url = reverse("payments:return", args=[self.order.public_id]) + "?payment_id=4040&status=approved&collection_status=approved"
        self.client.get(url)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.AWAITING_PAYMENT)

    def test_return_url_triggers_server_side_verification(self):
        self.gateway.add_payment(self.order, "5001")
        self.client.get(reverse("payments:return", args=[self.order.public_id]) + "?payment_id=5001")
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, OrderStatus.PAID)

    def test_checkout_redirects_to_gateway(self):
        v = f.variant(stock=5)
        self.client.post(reverse("cart:add"), {"variant_id": v.pk, "quantity": 1})
        data = {"email": "pagante@exemplo.com", "full_name": "Pagante", "phone": "11988887777", "cep": "05860-000",
                "street": "Rua", "number": "1", "neighborhood": "B", "city": "SP", "state": "SP",
                "shipping_code": f"m{self.method.pk}", "accept_terms": "on"}
        resp = self.client.post(reverse("cart:checkout"), data)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("https://sandbox.mercadopago.com.br"))
        self.assertTrue(Payment.objects.filter(preference_id__startswith="pref-").exists())

    def test_preference_payload_matches_total(self):
        from apps.payments.gateway import MercadoPagoGateway

        pref = MercadoPagoGateway(access_token="TEST").build_preference(self.order)
        items_total = sum(Decimal(str(i["unit_price"])) * i["quantity"] for i in pref["items"])
        shipping = Decimal(str(pref.get("shipments", {}).get("cost", 0)))
        self.assertEqual(items_total + shipping, self.order.total)
        self.assertEqual(pref["external_reference"], str(self.order.public_id))

    def test_cancelled_order_releases_stock(self):
        from apps.orders.services import cancel_order

        cancel_order(self.order, reason="teste")
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.reserved, 0)


@override_settings(MERCADOPAGO_WEBHOOK_SECRET="", DEBUG=False)
class WebhookWithoutSecretTests(TestCase):
    def test_production_without_secret_rejects(self):
        resp = self.client.post(reverse("payments:webhook") + "?data.id=1&type=payment", "{}", content_type="application/json")
        self.assertEqual(resp.status_code, 401)
