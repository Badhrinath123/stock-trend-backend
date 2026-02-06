from sqlalchemy.orm import Session
import models, schemas, auth

def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()

def get_user_by_username(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()

def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()

def get_user_by_username_or_email(db: Session, identifier: str):
    return db.query(models.User).filter(
        (models.User.username == identifier) | (models.User.email == identifier)
    ).first()

def create_user(db: Session, user: schemas.UserCreate):
    hashed_password = auth.get_password_hash(user.password)
    db_user = models.User(
        username=user.username, 
        email=user.email,
        password_hash=hashed_password
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

def get_stocks(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.Stock).offset(skip).limit(limit).all()

def create_stock(db: Session, stock: schemas.StockCreate):
    # Check if stock exists
    existing_stock = db.query(models.Stock).filter(models.Stock.symbol == stock.symbol).first()
    if existing_stock:
        return existing_stock
        
    db_stock = models.Stock(**stock.model_dump())
    db.add(db_stock)
    db.commit()
    db.refresh(db_stock)
    return db_stock

def get_watchlist(db: Session, user_id: int):
    return db.query(models.Watchlist).filter(models.Watchlist.user_id == user_id).all()

def add_to_watchlist(db: Session, watchlist: schemas.WatchlistCreate, user_id: int):
    # Check if already exists
    exists = db.query(models.Watchlist).filter(
        models.Watchlist.user_id == user_id,
        models.Watchlist.stock_id == watchlist.stock_id
    ).first()
    if exists:
        return exists
    
    db_watchlist = models.Watchlist(**watchlist.model_dump(), user_id=user_id)
    db.add(db_watchlist)
    db.commit()
    db.refresh(db_watchlist)
    return db_watchlist

def delete_from_watchlist(db: Session, user_id: int, stock_symbol: str):
    # Find stock first
    stock = db.query(models.Stock).filter(models.Stock.symbol == stock_symbol.upper()).first()
    if not stock:
        return False
        
    # Find watchlist entry
    db_watchlist = db.query(models.Watchlist).filter(
        models.Watchlist.user_id == user_id,
        models.Watchlist.stock_id == stock.id
    ).first()
    
    if db_watchlist:
        db.delete(db_watchlist)
        db.commit()
        return True
    return False

def update_user_password(db: Session, user: models.User, new_password: str):
    user.password_hash = auth.get_password_hash(new_password)
    db.commit()
    db.refresh(user)
    return user
