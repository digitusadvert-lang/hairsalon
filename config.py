# config.py
import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-secret-key-here-change-this'
    
    # Get the base directory of your project
    basedir = os.path.abspath(os.path.dirname(__file__))
    
    # Database configuration
    # This creates database in 'instance' folder (Flask convention)
    SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(basedir, 'instance', 'salon.db')}"
    
    # OR if you want it in the project root:
    # SQLALCHEMY_DATABASE_URI = f"sqlite:///{os.path.join(basedir, 'salon.db')}"
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Telegram
    TELEGRAM_BOT_TOKEN ='8557502090:AAGy9F6kjHmdhLCTPCaJmszzYboqkdp50y0'
    TELEGRAM_BOT_LINK = 'https://t.me/hsalonbot'