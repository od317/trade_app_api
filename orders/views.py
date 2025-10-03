# orders/views.py
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from decimal import Decimal
from rest_framework.decorators import api_view, permission_classes
from notifications.utils import send_order_notification

# Import models
from products.models import Cart, CartItem, Product
from accounts.models import User
from wallet.models import Wallet, Transaction
from .models import Order, OrderItem, OrderStatus, Refund

# Import services
from .services import CheckoutService, OrderService, RefundService

# Import serializers
from .serializers import OrderSerializer,OrderDetailSerializer

def calculate_penalty(created_at):
    time_elapsed = timezone.now() - created_at
    if time_elapsed < timezone.timedelta(hours=1):
        return Decimal('0.00')  # No penalty within 1 hour
    elif time_elapsed < timezone.timedelta(days=1):
        return Decimal('0.10')  # 10% penalty within 1 day
    else:
        return Decimal('0.15')  # 15% penalty after 1 day

class CheckoutView(APIView):
    def post(self, request):
        user = request.user
        try:
            cart = Cart.objects.get(user=user)
            if not cart.items.exists():
                return Response(
                    {"error": "Cart is empty", "detail": "No items found in cart"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            try:
                order = CheckoutService.process_checkout(user)
                return Response(
                    {"order_number": order.order_number},
                    status=status.HTTP_201_CREATED
                )
            except ValueError as e:
                return Response(
                    {"error": "Checkout error", "detail": str(e)},
                    status=status.HTTP_400_BAD_REQUEST
                )
            except Exception as e:
                import traceback
                traceback.print_exc()
                return Response(
                    {
                        "error": "Checkout failed",
                        "detail": str(e),
                        "type": type(e).__name__
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
        except Cart.DoesNotExist:
            return Response(
                {"error": "Cart not found", "detail": "No cart exists for this user"},
                status=status.HTTP_400_BAD_REQUEST
            )


class OrderListView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['status']
    
    def get_queryset(self):
        return Order.objects.filter(
            buyer=self.request.user
        ).prefetch_related(
            'items',
            'items__product',
            'items__seller'
        ).order_by('-created_at')

class OrderDetailView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request, pk):
        """
        Retrieve detailed information about a specific order
        """
        try:
            order = Order.objects.prefetch_related(
                'items',
                'items__product',
                'items__seller',
                'items__product__images'
            ).get(pk=pk)
            
            # Check if user has permission to view this order
            if order.buyer != request.user and not request.user.is_staff:
                return Response(
                    {"error": "You don't have permission to view this order"},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            serializer = OrderDetailSerializer(order, context={'request': request})
            return Response(serializer.data)
            
        except Order.DoesNotExist:
            return Response(
                {"error": "Order not found"},
                status=status.HTTP_404_NOT_FOUND
            )

class UpdateOrderStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        VALID_TRANSITIONS = {
            OrderStatus.CREATED: [OrderStatus.PROCESSING],
            OrderStatus.PROCESSING: [OrderStatus.SHIPPED],
            OrderStatus.SHIPPED: [OrderStatus.DELIVERED],  # Delivery doesn't auto-complete
            OrderStatus.DELIVERED: [OrderStatus.COMPLETED],  # Explicit completion needed
        }

        try:
            order = Order.objects.get(pk=pk, buyer=request.user)
            new_status = request.data.get('status')
            
            if new_status not in VALID_TRANSITIONS.get(order.status, []):
                return Response(
                    {"error": f"Cannot change status from {order.status} to {new_status}"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Update status and delivery timestamp
            order.status = new_status
            if new_status == OrderStatus.DELIVERED:
                order.delivered_at = timezone.now()
            order.save()
            
            notification_type = f'order_{new_status.lower()}'
            send_order_notification(order.buyer, order, notification_type)

            return Response({
                "status": order.status,
                "delivered_at": order.delivered_at,
                "message": "Order marked as delivered. Complete after 3 days." 
                if new_status == OrderStatus.DELIVERED 
                else "Status updated"
            })
            
        except Order.DoesNotExist:
            return Response({"error": "Order not found"}, status=status.HTTP_404_NOT_FOUND)


class CompleteOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        """Separate endpoint for completion after delivery"""
        try:
            order = Order.objects.get(pk=pk, buyer=request.user)
            
            if order.status != OrderStatus.DELIVERED:
                return Response(
                    {"error": "Order must be delivered before completion"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if not order.delivered_at:
                return Response(
                    {"error": "Delivery timestamp missing"},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
            if timezone.now() < order.delivered_at + timezone.timedelta(days=3):
                return Response(
                    {"error": "Refund window still active (3 days after delivery)"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Proceed with completion
            order = CheckoutService.complete_order(order.id)

            send_order_notification(order.buyer, order, 'order_completed')

            return Response({
                "status": order.status,
                "completed_at": order.completed_at
            })
            
        except Order.DoesNotExist:
            return Response({"error": "Order not found"}, status=status.HTTP_404_NOT_FOUND)


class CancelOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(
                    pk=pk,
                    buyer=request.user,
                    status__in=[OrderStatus.CREATED, OrderStatus.PROCESSING, OrderStatus.SHIPPED]
                )
                
                penalty_percentage = calculate_penalty(order.created_at)
                penalty_amount = (order.total_amount - order.delivery_fee) * penalty_percentage
                refund_amount = order.total_amount - penalty_amount - order.delivery_fee
                
                buyer_wallet = Wallet.objects.select_for_update().get(user=request.user)
                
                # Release escrow funds
                buyer_wallet.held_balance -= order.total_amount
                buyer_wallet.balance += refund_amount
                buyer_wallet.save()
                
                # Record transactions
                Transaction.objects.create(
                    wallet=buyer_wallet,
                    amount=refund_amount,
                    transaction_type=Transaction.TransactionType.REFUND,
                    description=f"Order cancellation ({penalty_percentage*100}% penalty + delivery fee kept)",
                    reference=f"ORDER_CANCEL_{order.order_number}",
                    is_successful=True
                )
                
                # Restock products
                for item in order.items.all():
                    product = Product.objects.select_for_update().get(pk=item.product.pk)
                    product.quantity += item.quantity
                    product.save()
                
                order.status = OrderStatus.CANCELLED
                order.save()

                send_order_notification(order.buyer, order, 'order_cancelled')

                return Response({
                    "status": "cancelled",
                    "refund_amount": str(refund_amount),
                    "penalty_percentage": str(penalty_percentage * 100) + "%",
                    "penalty_amount": str(penalty_amount),
                    "delivery_fee_kept": str(order.delivery_fee)
                })
                
        except Order.DoesNotExist:
            return Response(
                {"error": "Order cannot be cancelled (either doesn't exist or is in wrong status)"},
                status=status.HTTP_400_BAD_REQUEST
            )


class RequestRefundView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, pk):
        try:
            order = Order.objects.get(pk=pk, buyer=request.user)
            
            if order.status != OrderStatus.DELIVERED:
                return Response(
                    {"error": "Only delivered orders can be refunded"},
                    status=status.HTTP_400_BAD_REQUEST
                )
                
            if timezone.now() > order.delivered_at + timezone.timedelta(days=3):
                return Response(
                    {"error": "Refund window expired (3 days after delivery)"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Calculate expected refund with 10% penalty
            original_amount = order.total_amount - order.delivery_fee
            penalty_amount = original_amount * Decimal('0.10')
            refund_amount = original_amount - penalty_amount
            
            refund = Refund.objects.create(
                order=order,
                amount=original_amount,  # Store original amount before penalty
                reason=request.data.get('reason', ''),
                status='requested'
            )

            send_order_notification(order.buyer, order, 'refund_requested')

            return Response({
                "status": "requested",
                "refund_id": refund.id,
                "original_amount": str(original_amount),
                "penalty_note": "10% penalty will be applied",
                "penalty_amount": str(penalty_amount),
                "estimated_refund": str(refund_amount),
                "delivery_fee_kept": str(order.delivery_fee),
                "message": "Refund request submitted for admin approval"
            }, status=status.HTTP_201_CREATED)
            
        except Order.DoesNotExist:
            return Response(
                {"error": "Order not found or doesn't belong to you"},
                status=status.HTTP_404_NOT_FOUND
            )


class ProcessRefundView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request, pk):
        try:
            refund = Refund.objects.select_related('order').get(pk=pk)
            
            if refund.order.status == 'refunded':
                return Response(
                    {"error": "Order already refunded"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if refund.status != 'requested':
                return Response(
                    {"error": "Refund already processed"},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            if request.data.get('approve', False):
                try:
                    with transaction.atomic():
                        # Apply 10% penalty to refunds
                        penalty_percentage = Decimal('0.10')
                        penalty_amount = refund.amount * penalty_percentage
                        refund_amount = refund.amount - penalty_amount
                        
                        buyer_wallet = Wallet.objects.select_for_update().get(user=refund.order.buyer)
                        buyer_wallet.balance += refund_amount
                        buyer_wallet.held_balance -= refund.order.total_amount
                        buyer_wallet.save()
                        
                        Transaction.objects.create(
                            wallet=buyer_wallet,
                            amount=refund_amount,
                            transaction_type=Transaction.TransactionType.REFUND,
                            description=f"Refund for Order #{refund.order.order_number} (10% penalty applied)",
                            reference=f"REFUND_{refund.id}",
                            is_successful=True
                        )
                        
                        # Record penalty as platform income
                        platform_wallet = Wallet.objects.select_for_update().get(
                            user__role='admin'  # Assuming you have a platform admin wallet
                        )
                        platform_wallet.balance += penalty_amount
                        platform_wallet.save()
                        
                        Transaction.objects.create(
                            wallet=platform_wallet,
                            amount=penalty_amount,
                            transaction_type=Transaction.TransactionType.PENALTY,
                            description=f"Penalty from refund Order #{refund.order.order_number}",
                            reference=f"PENALTY_{refund.id}",
                            is_successful=True
                        )
                        
                        refund.amount = refund_amount  # Update with penalty deducted
                        refund.status = 'approved'
                        refund.processed_at = timezone.now()
                        refund.admin_notes = request.data.get('admin_notes', '')
                        refund.save()
                        
                        refund.order.status = OrderStatus.REFUNDED
                        refund.order.save()
                        
                        for item in refund.order.items.all():
                            item.product.quantity += item.quantity
                            item.product.save()
                       
                        send_order_notification(
                            refund.order.buyer, 
                            refund.order, 
                            'refund_approved' if refund.status == 'approved' else 'refund_rejected'
                        )
                       
                        return Response({
                            "status": "approved",
                            "original_amount": str(refund.amount + penalty_amount),
                            "penalty_percentage": "10%",
                            "penalty_amount": str(penalty_amount),
                            "final_refund_amount": str(refund_amount),
                            "delivery_fee_kept": str(refund.order.delivery_fee)
                        })
                        
                except Exception as e:
                    return Response(
                        {"error": f"Refund processing failed: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR
                    )
            else:
                refund.status = 'rejected'
                refund.processed_at = timezone.now()
                refund.admin_notes = request.data.get('admin_notes', '')
                refund.save()

                send_order_notification(refund.order.buyer, refund.order, 'refund_rejected')
               
                return Response({
                    "status": "rejected",
                    "message": "Refund request denied"
                })
                
        except Refund.DoesNotExist:
            return Response(
                {"error": "Refund request not found"},
                status=status.HTTP_404_NOT_FOUND
            )


class OverdueOrdersView(APIView):
    permission_classes = [IsAdminUser]
    
    def get(self, request):
        overdue_orders = Order.objects.filter(
            status=OrderStatus.DELIVERED,
            delivered_at__lte=timezone.now() - timezone.timedelta(days=3)
        ).select_related('buyer').prefetch_related('items')
        
        data = []
        for order in overdue_orders:
            data.append({
                "order_id": order.id,
                "order_number": order.order_number,
                "buyer": order.buyer.email,
                "delivered_at": order.delivered_at,
                "total_amount": str(order.total_amount),
                "items": [{
                    "product": item.product.name_en,
                    "quantity": item.quantity,
                    "seller": item.seller.email
                } for item in order.items.all()]
            })
        
        return Response({
            "count": len(data),
            "results": data
        })
    

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def force_complete_order(request, order_id):
    try:
        order = Order.objects.get(pk=order_id)
    except Order.DoesNotExist:
        return Response({"error": "Order not found"}, status=404)

    # 1. Simulate that the order was delivered 4 days ago
    order.status = OrderStatus.DELIVERED
    order.delivered_at = timezone.now() - timezone.timedelta(days=4)
    order.save(update_fields=["status", "delivered_at"])

    # 2. Call the exact same service method used in production
    from orders.services import CheckoutService
    try:
        completed_order = CheckoutService.complete_order(order.id)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)

    return Response({
        "status": "completed",
        "order_id": completed_order.id,
        "completed_at": completed_order.completed_at
    })
