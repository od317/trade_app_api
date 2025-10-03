# analytics_admin/urls.py
from django.urls import path
from .views import (
    AdminDashboardSummaryView,
    AdminSalesOverTimeView,
    AdminTopSellersByPointsView,
    AdminTopProductsView,
    AdminTopBuyersView,
    AdminReturnsBreakdownView,
    AdminRatingsDistributionView,
    AdminLowStockView,
    AdminBrandsStatsView,
    AdminAuctionsStatsView,
    CheckAdminToken
)

urlpatterns = [
    path('summary/', AdminDashboardSummaryView.as_view()),
    path('check-admin-token/', CheckAdminToken.as_view()),
    path('sales-over-time/', AdminSalesOverTimeView.as_view()),
    path('top-sellers/', AdminTopSellersByPointsView.as_view()),          # ?limit=10
    path('top-products/', AdminTopProductsView.as_view()),                # ?metric=revenue|quantity&from=&to=&limit=
    path('top-buyers/', AdminTopBuyersView.as_view()),                    # ?metric=spend|orders&from=&to=&limit=
    path('returns-breakdown/', AdminReturnsBreakdownView.as_view()),      # ?from=&to=
    path('ratings/', AdminRatingsDistributionView.as_view()),
    path('low-stock/', AdminLowStockView.as_view()),                      # ?threshold=5&limit=50
    path('brands-stats/', AdminBrandsStatsView.as_view()),
    path('auctions-stats/', AdminAuctionsStatsView.as_view()),
]
