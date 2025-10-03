# auctions/services.py
from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from .models import Auction, Bid, AuctionStatus
from wallet.models import Wallet, Transaction
from notifications.models import Notification
from orders.models import Order, OrderItem, OrderStatus
from rest_framework.exceptions import ValidationError

User = get_user_model()


def _current_top(auction: Auction):
    top = auction.bids.order_by('-amount', '-created_at').first()
    return (top.bidder if top else None), (top.amount if top else None)


@transaction.atomic
def activate_scheduled_if_due(auction_id: int) -> bool:
    auction = Auction.objects.select_for_update().get(pk=auction_id)
    now = timezone.now()
    if auction.status == AuctionStatus.APPROVED and auction.start_at <= now < auction.end_at:
        auction.status = AuctionStatus.ACTIVE
        auction.save(update_fields=['status'])
        return True
    return False


@transaction.atomic
def place_bid(auction_id: int, bidder: User, amount: Decimal):
    auction = Auction.objects.select_for_update().get(pk=auction_id)

    # live window check
    now = timezone.now()
    if auction.status != AuctionStatus.ACTIVE or not (auction.start_at <= now < auction.end_at):
        raise ValidationError("Auction is not active.")

    if bidder_id := getattr(bidder, "id", None):
        if bidder_id == auction.seller_id:
            raise ValidationError("Seller cannot bid on their own auction.")

    # enforce min increment
    curr_leader, curr_amount = _current_top(auction)
    min_allowed = auction.start_price if curr_amount is None else (curr_amount + auction.min_increment)
    if amount < min_allowed:
        raise ValidationError(f"Bid must be at least {min_allowed}.")

    # bidder wallet
    bidder_wallet = Wallet.objects.select_for_update().get(user=bidder)

    # how much to newly move into held?
    if curr_leader and curr_leader.id == bidder.id:
        top_up = amount - curr_amount
        if top_up <= 0:
            raise ValidationError("New bid must exceed your current highest bid.")
    else:
        top_up = amount

    if bidder_wallet.balance < top_up:
        raise ValidationError("Insufficient wallet balance to place this bid.")

    # move top-up from balance -> held
    bidder_wallet.balance -= top_up
    bidder_wallet.held_balance += top_up
    bidder_wallet.save()
    Transaction.objects.create(
        wallet=bidder_wallet,
        amount=-top_up,
        transaction_type=Transaction.TransactionType.ESCROW_HOLD,
        description=f"Bid hold for Auction #{auction.id}",
        reference=f"BID_HOLD_{auction.id}",
        is_successful=True
    )

    # release previous leader (if different)
    if curr_leader and curr_leader.id != bidder.id:
        prev_wallet = Wallet.objects.select_for_update().get(user=curr_leader)
        prev_wallet.held_balance -= curr_amount
        prev_wallet.balance += curr_amount
        prev_wallet.save()
        Transaction.objects.create(
            wallet=prev_wallet,
            amount=curr_amount,
            transaction_type=Transaction.TransactionType.REFUND,
            description=f"Outbid refund (Auction #{auction.id})",
            reference=f"OUTBID_REFUND_{auction.id}",
            is_successful=True
        )
        # notify previous leader
        Notification.objects.create(
            user=curr_leader,
            notification_type='auction_outbid',
            message_ar=f"تمت المزايدة عليك في المزاد #{auction.id} بمبلغ أعلى.",
            message_en=f"You've been outbid on auction #{auction.id}.",
            content_object=auction
        )

    # record bid
    bid = Bid.objects.create(auction=auction, bidder=bidder, amount=amount)

    # anti-sniping auto-extend
    time_left = (auction.end_at - now).total_seconds()
    if time_left <= auction.auto_extend_window_seconds:
        auction.end_at = auction.end_at + timezone.timedelta(seconds=auction.auto_extend_seconds)
        auction.save(update_fields=['end_at'])

    # notify seller
    Notification.objects.create(
        user=auction.seller,
        notification_type='auction_new_bid',
        message_ar=f"مزايدة جديدة على مزادك #{auction.id}: {amount}.",
        message_en=f"New bid on your auction #{auction.id}: {amount}.",
        content_object=auction
    )

    return bid


def _final_highest_bids_by_bidder(auction: Auction):
    """
    Dict {bidder_id: max_amount}. Traverse once, keep first (highest) per bidder.
    """
    highest = {}
    for b in Bid.objects.filter(auction=auction).order_by('-amount', '-created_at'):
        if b.bidder_id not in highest:
            highest[b.bidder_id] = b.amount
    return highest


def _release_hold(user: User, amount: Decimal, auction: Auction, note: str):
    if amount <= 0:
        return
    w = Wallet.objects.select_for_update().get(user=user)
    w.held_balance -= amount
    w.balance += amount
    w.save()
    Transaction.objects.create(
        wallet=w,
        amount=amount,
        transaction_type=Transaction.TransactionType.REFUND,
        description=f"{note} (Auction #{auction.id})",
        reference=f"AUCTION_RELEASE_{auction.id}",
        is_successful=True,
    )


def _convert_winner_hold_to_escrow(user: User, auction: Auction):
    """
    Funds are already in 'held_balance' from bidding. No balance change.
    We just create a zero-amount bookkeeping entry to mark escrow continuity.
    """
    w = Wallet.objects.select_for_update().get(user=user)
    Transaction.objects.create(
        wallet=w,
        amount=Decimal('0.00'),
        transaction_type=Transaction.TransactionType.ESCROW_HOLD,
        description=f"Converted bid hold to escrow hold for Auction #{auction.id}",
        reference=f"ESCROW_HOLD_AUCTION_{auction.id}",
        is_successful=True,
    )


@transaction.atomic
def admin_close_auction(auction_id: int, admin_user: User):
    """
    Manually close an auction:
    - Decide winner (if reserve met)
    - Release all losers’ holds
    - Keep winner’s hold and create Order
    - Restock if no sale
    """
    auction = Auction.objects.select_for_update().get(pk=auction_id)

    # allow closing in ACTIVE/APPROVED/SUBMITTED (manual, since no scheduler)
    bids_qs = Bid.objects.filter(auction=auction).order_by('-amount', '-created_at')
    winner_bid = bids_qs.first()
    reserve = auction.reserve_price

    final_by_bidder = _final_highest_bids_by_bidder(auction)

    # No sale case
    if not winner_bid or (reserve and winner_bid.amount < reserve):
        for bidder_id, held_amt in final_by_bidder.items():
            bidder = User.objects.get(pk=bidder_id)
            _release_hold(bidder, held_amt, auction, note="Auction ended without sale")

        auction.status = AuctionStatus.ENDED
        auction.cancelled_at = timezone.now()
        auction.cancelled_by = admin_user
        auction.save()

        # restore reserved stock
        product = auction.product
        product.quantity += auction.quantity
        product.save()

        Notification.objects.create(
            user=auction.seller,
            notification_type='auction_ended_no_sale',
            message_ar=f"انتهى المزاد #{auction.id} بدون بيع.",
            message_en=f"Auction #{auction.id} ended with no sale.",
            content_object=auction,
        )
        return {"status": "ended_no_sale"}

    # There is a winner
    winner = winner_bid.bidder
    winning_amount = winner_bid.amount

    # release losers
    for bidder_id, held_amt in final_by_bidder.items():
        if bidder_id == winner.id:
            continue
        bidder = User.objects.get(pk=bidder_id)
        _release_hold(bidder, held_amt, auction, note="Outbid refund / auction ended")
        Notification.objects.create(
            user=bidder,
            notification_type='auction_lost',
            message_ar=f"انتهى المزاد #{auction.id} ولم تربح.",
            message_en=f"Auction #{auction.id} has ended and you did not win.",
            content_object=auction
        )

    # keep winner hold (no balance change), mark escrow continuity
    _convert_winner_hold_to_escrow(winner, auction)

    # create order for winner
    order = Order.objects.create(
        buyer=winner,
        total_amount=winning_amount,
        delivery_fee=Decimal('0.00'),
        status=OrderStatus.CREATED,
    )
    OrderItem.objects.create(
        order=order,
        product=auction.product,
        seller=auction.seller,
        quantity=auction.quantity,
        price_at_purchase=winning_amount,
        total_price=winning_amount,
    )

    # mark auction ended
    auction.status = AuctionStatus.ENDED
    auction.cancelled_at = timezone.now()
    auction.cancelled_by = admin_user
    auction.save()

    # notifications
    Notification.objects.create(
        user=winner,
        notification_type='auction_won',
        message_ar=f"ربحت المزاد #{auction.id} بمبلغ {winning_amount}. تم إنشاء طلب جديد.",
        message_en=f"You won auction #{auction.id} for {winning_amount}. A new order was created.",
        content_object=order,
    )
    Notification.objects.create(
        user=auction.seller,
        notification_type='auction_sold',
        message_ar=f"تم بيع المزاد #{auction.id} بمبلغ {winning_amount}. تم إنشاء طلب للعميل.",
        message_en=f"Auction #{auction.id} sold for {winning_amount}. An order has been created.",
        content_object=order,
    )

    return {"status": "ended_sold", "order_id": order.id}


@transaction.atomic
def cancel_auction(auction_id: int, actor: User, is_admin=False):
    """Cancel an auction. Admin can cancel anytime; seller only if no bids and not active."""
    auction = Auction.objects.select_for_update().get(pk=auction_id)

    if not is_admin:
        # seller rules
        if not (auction.status in [AuctionStatus.SUBMITTED, AuctionStatus.APPROVED] and auction.bids.count() == 0):
            raise ValidationError("Seller cannot cancel this auction at current state.")

    # release current top if any
    top_bid = auction.bids.order_by('-amount', '-created_at').first()
    if top_bid:
        w = Wallet.objects.select_for_update().get(user=top_bid.bidder)
        w.held_balance -= top_bid.amount
        w.balance += top_bid.amount
        w.save()
        Transaction.objects.create(
            wallet=w,
            amount=top_bid.amount,
            transaction_type=Transaction.TransactionType.REFUND,
            description=f"Auction cancelled #{auction.id}",
            reference=f"AUCT_CANCEL_{auction.id}",
            is_successful=True
        )
        Notification.objects.create(
            user=top_bid.bidder,
            notification_type='auction_cancelled',
            message_ar=f"تم إلغاء المزاد {auction.title}. تم تحرير الأموال المحتجزة.",
            message_en=f"Auction {auction.title} was cancelled. Your held funds were released.",
            content_object=auction
        )

    # restore reserved stock
    product = auction.product
    product.quantity += auction.quantity
    product.save()

    auction.status = AuctionStatus.CANCELLED
    auction.cancelled_at = timezone.now()
    auction.cancelled_by = actor
    auction.save(update_fields=['status', 'cancelled_at', 'cancelled_by'])

    Notification.objects.create(
        user=auction.seller,
        notification_type='auction_cancelled',
        message_ar=f"تم إلغاء المزاد {auction.title}.",
        message_en=f"Auction {auction.title} was cancelled.",
        content_object=auction
    )
    return auction

@transaction.atomic
def buy_now(auction_id: int, buyer: User):
    """
    Allow a user to buy an auction item immediately at the buy_now_price
    """
    auction = Auction.objects.select_for_update().get(pk=auction_id)
    
    # Check if auction is active
    now = timezone.now()
    if auction.status != AuctionStatus.ACTIVE or not (auction.start_at <= now < auction.end_at):
        raise ValidationError("Auction is not active.")
    
    # Check if buy now is available
    if not auction.buy_now_price:
        raise ValidationError("Buy now is not available for this auction.")
    
    # Check if user is not the seller
    if buyer.id == auction.seller_id:
        raise ValidationError("Seller cannot buy their own auction.")
    
    # Check if there are no existing bids (optional: you might want to allow buy now even with bids)
    if auction.bids.exists():
        raise ValidationError("Buy now is not available after bidding has started.")
    
    # Check buyer's wallet balance
    buyer_wallet = Wallet.objects.select_for_update().get(user=buyer)
    if buyer_wallet.balance < auction.buy_now_price:
        raise ValidationError("Insufficient wallet balance to buy this item.")
    
    # Process payment
    buyer_wallet.balance -= auction.buy_now_price
    buyer_wallet.save()
    
    Transaction.objects.create(
        wallet=buyer_wallet,
        amount=-auction.buy_now_price,
        transaction_type=Transaction.TransactionType.PURCHASE,
        description=f"Buy now purchase for Auction #{auction.id}",
        reference=f"BUY_NOW_{auction.id}",
        is_successful=True
    )
    
    # End the auction
    auction.status = AuctionStatus.ENDED
    auction.cancelled_at = now
    auction.save()
    
    # Create order
    order = Order.objects.create(
        buyer=buyer,
        total_amount=auction.buy_now_price,
        delivery_fee=Decimal('0.00'),
        status=OrderStatus.CREATED,
    )
    
    OrderItem.objects.create(
        order=order,
        product=auction.product,
        seller=auction.seller,
        quantity=auction.quantity,
        price_at_purchase=auction.buy_now_price,
        total_price=auction.buy_now_price,
    )
    
    # Notifications
    Notification.objects.create(
        user=buyer,
        notification_type='auction_bought',
        message_ar=f"اشتريت المزاد #{auction.id} بسعر الشراء الفوري {auction.buy_now_price}.",
        message_en=f"You bought auction #{auction.id} for {auction.buy_now_price} using buy now.",
        content_object=order,
    )
    
    Notification.objects.create(
        user=auction.seller,
        notification_type='auction_sold_buy_now',
        message_ar=f"تم بيع المزاد #{auction.id} عبر الشراء الفوري بمبلغ {auction.buy_now_price}.",
        message_en=f"Auction #{auction.id} was sold via buy now for {auction.buy_now_price}.",
        content_object=order,
    )
    
    # Release any existing bids (though there shouldn't be any if you prevent buy now after bidding)
    final_by_bidder = _final_highest_bids_by_bidder(auction)
    for bidder_id, held_amt in final_by_bidder.items():
        if bidder_id != buyer.id:  # Don't release buyer's funds since they're used for purchase
            bidder = User.objects.get(pk=bidder_id)
            _release_hold(bidder, held_amt, auction, note="Auction ended via buy now")
    
    return {"status": "sold_via_buy_now", "order_id": order.id}