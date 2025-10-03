from django.urls import path
from .views import (
    ReturnRequestListView,
    ReturnRequestCreateView,
    ReturnRequestImageUploadView,
    ReturnRequestAdminUpdateView,
    ReturnRequestAdminListView,
    MultiStatusReturnProcessView,
    ReturnedProductSellerApprovalView,
    SellerReturnedProductsView,
    ReturnRequestRejectView,
    RefundWholeOrderView
)

urlpatterns = [
    path('my-requests/', ReturnRequestListView.as_view(), name='return-request-list'),
    path('request/', ReturnRequestCreateView.as_view(), name='return-request-create'),
    path('upload-image/<int:return_request_id>/', ReturnRequestImageUploadView.as_view(), name='return-request-image-upload'),
    path('admin/<int:pk>/update/', ReturnRequestAdminUpdateView.as_view(), name='return-request-admin-update'),
    path('admin/all/', ReturnRequestAdminListView.as_view(), name='return-request-admin-list'),
    path('return-request/<int:return_request_id>/multi-status-process/', MultiStatusReturnProcessView.as_view(), name='multi-status-process'),
    path('returned-product/<int:pk>/seller-approval/', ReturnedProductSellerApprovalView.as_view(), name='returned-product-seller-approval'),
    path('my-returned-products/', SellerReturnedProductsView.as_view(), name='my-returned-products'),
    path('return-request/<int:pk>/reject/', ReturnRequestRejectView.as_view(), name='return-request-reject'),
    path('order/<int:order_id>/refund-all/', RefundWholeOrderView.as_view(), name='refund-whole-order'),
    path('seller/returned-products/', SellerReturnedProductsView.as_view(), name='seller-returned-products'),
]