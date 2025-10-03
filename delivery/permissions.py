# delivery/permissions.py
from rest_framework.permissions import BasePermission

class IsDelivery(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and getattr(user, 'role', '') == 'delivery'
