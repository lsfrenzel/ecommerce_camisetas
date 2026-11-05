from django.contrib import admin

from .models import Coupon, CouponRedemption, Promotion

admin.site.register([Coupon, CouponRedemption, Promotion])
