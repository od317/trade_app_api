# analytics/urls.py
from django.urls import path
from .views import (
    SellerDashboardSummaryView, SellerOrdersOverTimeView, SellerTopProductsView,
    SellerLowStockView, SellerReturnsStatsView, SellerRatingsBreakdownView,
    SellerAuctionStatsView
)

urlpatterns = [
    path('seller/summary/', SellerDashboardSummaryView.as_view()),
    path('seller/orders-over-time/', SellerOrdersOverTimeView.as_view()),
    path('seller/top-products/', SellerTopProductsView.as_view()),
    path('seller/low-stock/', SellerLowStockView.as_view()),
    path('seller/returns/', SellerReturnsStatsView.as_view()),
    path('seller/ratings/', SellerRatingsBreakdownView.as_view()),
    path('seller/auctions/', SellerAuctionStatsView.as_view()),
]
