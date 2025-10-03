# auctions/tasks.py
from celery import shared_task
from auctions.services import activate_due_auctions, close_due_auctions

@shared_task
def activate_due_auctions_task():
    activate_due_auctions()

@shared_task
def close_due_auctions_task():
    close_due_auctions()
