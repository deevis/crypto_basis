import csv
from datetime import datetime
from models import Transaction, OperationType
from db_config import SessionLocal

def safe_float(value, default=0.0):
    """Convert string to float, returning default if value is empty or invalid"""
    try:
        return float(value) if value.strip() else default
    except (ValueError, AttributeError):
        return default

def import_csv(file_path):
    session = SessionLocal()
    
    with open(file_path, 'r') as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            operation_amount = safe_float(row['Operation Amount'])
            operation_type = OperationType(row['Operation Type'])
            
            transaction = Transaction(
                wallet_name=row['wallet_name'],
                countervalue_ticker=row['Countervalue Ticker'],
                currency_ticker=row['Currency Ticker'],
                operation_type=operation_type,
                operation_date=datetime.strptime(row['Operation Date'], '%Y-%m-%dT%H:%M:%S.%fZ'),
                operation_amount=operation_amount,
                operation_fees=safe_float(row['Operation Fees']),
                cost_basis_minus_fees=safe_float(row['cost_basis_minus_fees']),
                cost_basis=safe_float(row['cost_basis']),
                status=row['Status'],
                account_name=row['Account Name'],
                account_xpub=row['Account xpub'],
                countervalue_at_operation=safe_float(row['Countervalue at Operation Date']),
                operation_hash=row['Operation Hash'],
                available_to_spend=operation_amount if operation_type == OperationType.IN else None
            )
            session.add(transaction)
            
        session.commit() 