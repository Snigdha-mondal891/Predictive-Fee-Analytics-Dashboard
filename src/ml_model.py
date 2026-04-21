import pandas as pd
import numpy as np
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error
import os

def create_features(df):
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp')
    
    # Time-series features
    df['hour'] = df['timestamp'].dt.hour
    df['day_of_week'] = df['timestamp'].dt.dayofweek
    df['is_weekend'] = df['day_of_week'] >= 5
    
    # Lag features
    df['lag_1h_fee'] = df['max_fee_bid'].shift(1)
    df['lag_2h_fee'] = df['max_fee_bid'].shift(2)
    df['lag_24h_fee'] = df['max_fee_bid'].shift(24)
    
    # Moving averages
    df['ma_6h_fee'] = df['max_fee_bid'].rolling(window=6).mean()
    df['ma_24h_fee'] = df['max_fee_bid'].rolling(window=24).mean()
    
    df = df.dropna()
    return df

def train_model():
    print("Loading data...")
    df = pd.read_csv('data/historical_fees.csv')
    df = create_features(df)
    
    features = ['hour', 'day_of_week', 'is_weekend', 'lag_1h_fee', 'lag_24h_fee', 'ma_6h_fee', 'ma_24h_fee', 'avg_operation_count', 'ledger_capacity_usage']
    target = 'max_fee_bid'
    
    X = df[features]
    y = df[target]
    
    print("Training XGBoost model...")
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
    
    model = xgb.XGBRegressor(n_estimators=100, learning_rate=0.1, max_depth=5, random_state=42)
    model.fit(X_train, y_train)
    
    predictions = model.predict(X_test)
    mae = mean_absolute_error(y_test, predictions)
    
    print(f"Model trained successfully. Mean Absolute Error (MAE): {mae:.2f} stroops")
    
    os.makedirs('models', exist_ok=True)
    model.save_model('models/xgb_fee_model.json')
    print("Model saved to models/xgb_fee_model.json")
    
if __name__ == "__main__":
    train_model()
