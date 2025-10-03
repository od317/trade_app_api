# permissions.py
from rest_framework.permissions import BasePermission
from enum import Enum

class IsSuperAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.is_superuser

class IsSeller(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'seller'

class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'admin'
class IsUser(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'user'
class Isdelivery(BasePermission):
    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role == 'delivery'

class UserRole(Enum):
    SUPERADMIN = 'superadmin'
    ADMIN = 'admin'
    DELIVERY = 'delivery'
    USER = 'user'
    SELLER = 'seller'

class IsSuperAdminOrAdmin(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return (
            user.is_authenticated and
            user.role in (UserRole.SUPERADMIN.value, UserRole.ADMIN.value)
        )    
class IsBuyerOrSeller(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return (
            user.is_authenticated and
            user.role in (UserRole.SELLER.value, UserRole.USER.value)
        )        