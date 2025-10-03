# views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from django.shortcuts import get_object_or_404
from .models import Notification
from .serializers import NotificationSerializer
from django.utils import timezone
from django.db.models import Q

class NotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100

class NotificationListView(APIView):
    """
    List all notifications for the authenticated user with pagination
    Supports filtering by read/unread status and notification type
    """
    permission_classes = [IsAuthenticated]
    pagination_class = NotificationPagination

    def get(self, request):
        # Get query parameters
        is_read = request.query_params.get('is_read', None)
        notification_type = request.query_params.get('type', None)
        page_size = request.query_params.get('page_size', 20)
        
        # Base queryset
        notifications = request.user.user_notifications.all().order_by('-created_at')
        
        # Apply filters
        if is_read is not None:
            notifications = notifications.filter(is_read=is_read.lower() == 'true')
        if notification_type:
            notifications = notifications.filter(notification_type=notification_type)
        
        # Paginate results
        paginator = self.pagination_class()
        paginator.page_size = page_size
        result_page = paginator.paginate_queryset(notifications, request)
        
        serializer = NotificationSerializer(result_page, many=True)
        
        return paginator.get_paginated_response(serializer.data)


class MarkAsReadView(APIView):
    """
    Mark a specific notification as read
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id):
        notification = get_object_or_404(
            Notification,
            id=notification_id,
            user=request.user
        )
        
        notification.mark_as_read()
        
        return Response({
            'status': 'marked as read',
            'read_at': notification.read_at
        }, status=status.HTTP_200_OK)


class UnreadCountView(APIView):
    """
    Get count of unread notifications
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        count = request.user.user_notifications.filter(is_read=False).count()
        return Response({'unread_count': count})


class MarkAllAsReadView(APIView):
    """
    Mark all notifications as read for the user
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        updated_count = request.user.user_notifications.filter(is_read=False).update(
            is_read=True,
            read_at=timezone.now()
        )
        return Response({
            'status': 'success',
            'message': f'Marked {updated_count} notifications as read',
            'read_count': updated_count
        })


class NotificationDetailView(APIView):
    """
    Retrieve a specific notification and mark as read when viewed
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, notification_id):
        notification = get_object_or_404(
            Notification,
            id=notification_id,
            user=request.user
        )
        
        # Mark as read when retrieved
        notification.mark_as_read()
            
        serializer = NotificationSerializer(notification)
        return Response(serializer.data)