import pandas as pd
import numpy as np
import xgboost as xgb
from datetime import datetime, timedelta

class BatchingOptimizer:
    def __init__(self, model_path='models/xgb_fee_model.json', data_path='data/historical_fees.csv'):
        self.model = xgb.XGBRegressor()
        self.model.load_model(model_path)
        self.df = pd.read_csv(data_path)
        self.df['timestamp'] = pd.to_datetime(self.df['timestamp'])
        
    def forecast_fees_for_window(self, max_wait_time_minutes=60):
        # We need recent state to feed the lag features
        recent_data = self.df.sort_values('timestamp').tail(24).copy()
        
        current_time = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        
        # Predict the next N hours covering max_wait_time_minutes
        forecast_hours = max(1, max_wait_time_minutes // 60 + 1)
        
        forecasts = []
        
        # Iterative forecasting
        for i in range(forecast_hours):
            target_time = current_time + timedelta(hours=i+1)
            
            # Build features
            f_hour = target_time.hour
            f_dow = target_time.dayofweek
            f_weekend = f_dow >= 5
            
            # Get latest lags
            f_lag1 = recent_data['max_fee_bid'].iloc[-1]
            f_lag24 = recent_data['max_fee_bid'].iloc[-24]
            f_ma6 = recent_data['max_fee_bid'].tail(6).mean()
            f_ma24 = recent_data['max_fee_bid'].tail(24).mean()
            
            # Using typical capacity for that hour of week
            typical_stats = self.df[(self.df['hour'] == f_hour) & (self.df['day_of_week'] == f_dow)]
            f_avg_ops = typical_stats['avg_operation_count'].mean() if not typical_stats.empty else 50
            f_cap = typical_stats['ledger_capacity_usage'].mean() if not typical_stats.empty else 0.5
            
            features = pd.DataFrame([{
                'hour': f_hour,
                'day_of_week': f_dow,
                'is_weekend': f_weekend,
                'lag_1h_fee': f_lag1,
                'lag_24h_fee': f_lag24,
                'ma_6h_fee': f_ma6,
                'ma_24h_fee': f_ma24,
                'avg_operation_count': f_avg_ops,
                'ledger_capacity_usage': f_cap
            }])
            
            pred_fee = self.model.predict(features)[0]
            
            forecasts.append({'timestamp': target_time, 'predicted_fee': pred_fee})
            
            # Update recent_data with prediction for next step
            new_row = pd.DataFrame([{'timestamp': target_time, 'max_fee_bid': pred_fee}])
            recent_data = pd.concat([recent_data, new_row]).reset_index(drop=True)
            
        return pd.DataFrame(forecasts)
        
    def find_optimal_batch_time(self, pending_txs, max_wait_time_minutes):
        forecast_df = self.forecast_fees_for_window(max_wait_time_minutes)
        min_fee_row = forecast_df.loc[forecast_df['predicted_fee'].idxmin()]
        
        return {
            'optimal_time': min_fee_row['timestamp'],
            'predicted_fee': float(min_fee_row['predicted_fee']),
            'total_estimated_cost': float(min_fee_row['predicted_fee']) * len(pending_txs),
            'forecast': forecast_df.to_dict('records')
        }
