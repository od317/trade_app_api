# urls.py
from django.urls import path
from .views import (
    NotificationListView,
    MarkAsReadView,
    UnreadCountView,
    MarkAllAsReadView,
    NotificationDetailView
)

urlpatterns = [
    path('', NotificationListView.as_view(), name='notification-list'),
    path('<int:notification_id>/', NotificationDetailView.as_view(), name='notification-detail'),
    path('<int:notification_id>/read/', MarkAsReadView.as_view(), name='mark-read'),
    path('unread-count/', UnreadCountView.as_view(), name='unread-count'),
    path('mark-all-read/', MarkAllAsReadView.as_view(), name='mark-all-read'),
]