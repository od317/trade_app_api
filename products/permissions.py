from rest_framework.permissions import BasePermission

class IsSeller(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'seller'

class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_staff

class IsSellerOrAdmin(BasePermission):
    def has_permission(self, request, view):
        return IsSeller().has_permission(request, view) or IsAdmin().has_permission(request, view)