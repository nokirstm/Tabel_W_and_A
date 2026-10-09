"""
sync_client.py - Сетевой слой для синхронизации с сервером
Версия 2.0.0
"""
import os
import json
import uuid
import requests
import threading

class SyncClient:
    """Клиент для синхронизации с сервером через Google Apps Script API."""
    
    def __init__(self, api_url, api_token, device_id_file):
        self.api_url = api_url
        self.api_token = api_token
        self.device_id_file = device_id_file
        self.device_id = self._load_or_create_device_id()
        self.employee_id = None
        self.employee_token = None
        
    def _load_or_create_device_id(self):
        """Загружает device_id из файла или создает новый."""
        if os.path.exists(self.device_id_file):
            try:
                with open(self.device_id_file, 'r') as f:
                    device_id = f.read().strip()
                    if device_id:
                        return device_id
            except Exception:
                pass
        
        device_id = str(uuid.uuid4())
        try:
            with open(self.device_id_file, 'w') as f:
                f.write(device_id)
        except Exception:
            pass
        return device_id
    
    def set_credentials(self, employee_id, employee_token):
        """Устанавливает credentials сотрудника."""
        self.employee_id = employee_id
        self.employee_token = employee_token
        
    def _make_request(self, command, payload=None, employee_id=None, employee_token=None):
        """Базовый метод для отправки команд на сервер."""
        data = {
            'api_token': self.api_token,
            'command': command,
            'device_id': self.device_id,
            'request_id': str(uuid.uuid4())
        }
        if payload:
            data['payload'] = payload
        if employee_id:
            data['employee_id'] = employee_id
        if employee_token:
            data['employee_token'] = employee_token
            
        try:
            response = requests.post(self.api_url, json=data, timeout=15)
            if response.status_code == 200:
                return response.json()
            else:
                return {'ok': False, 'error': f'HTTP {response.status_code}'}
        except requests.exceptions.Timeout:
            return {'ok': False, 'error': 'timeout'}
        except requests.exceptions.ConnectionError:
            return {'ok': False, 'error': 'no_connection'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}
    
    def create_account(self, name, birth_date):
        """Создание новой учетной записи."""
        payload = {
            'name': name,
            'birth_date': birth_date
        }
        return self._make_request('create_account', payload)
    
    def bind_device(self, employee_token, name=None, birth_date=None):
        """Привязка устройства к существующему сотруднику."""
        payload = {'employee_token': employee_token}
        if name and birth_date:
            payload['name'] = name
            payload['birth_date'] = birth_date
        return self._make_request('bind_device', payload)
    
    def restore_account(self, name, birth_date, device_type="android"):
        """Восстановление учетной записи на новом устройстве.
        device_type: 'android' или 'windows' (роль устройства в протоколе)."""
        payload = {
            'name': name,
            'birth_date': birth_date,
            'device_type': device_type
        }
        return self._make_request('restore_account', payload)
    
    def day_updated(self, employee_id, employee_token, date, entry_dict, version):
        """Отправка уведомления об обновлении дня."""
        payload = {
            'date': date,
            'version': version,
            'entry': entry_dict
        }
        return self._make_request('day_updated', payload, employee_id, employee_token)
    
    def day_approved(self, employee_id, employee_token, date, version):
        """Одобрение дня начальником. Отправляет только Windows."""
        payload = {
            'date': date,
            'version': version
        }
        return self._make_request('day_approved', payload, employee_id, employee_token)
    
    def payment_date_entered(self, employee_id, employee_token, week_id, payment_date, version):
        """Отправка уведомления о вводе даты выплаты."""
        payload = {
            'week_id': week_id,
            'payment_date': payment_date,
            'version': version
        }
        return self._make_request('payment_date_entered', payload, employee_id, employee_token)
    
    def payment_received(self, employee_id, employee_token, week_id, *args):
        """Подтверждение получения выплаты.
        Терпит обе формы вызова:
        (emp_id, emp_token, week_id, version) и
        (emp_id, emp_token, week_id, payload_dict, version) — как вызывает android/main.py."""
        extra = {}
        version = 0
        for a in args:
            if isinstance(a, dict):
                extra.update(a)
            elif isinstance(a, (int, str)):
                version = a
        payload = {
            'week_id': week_id,
            'payment_confirmed': True,
            'version': version
        }
        if extra.get('payment_date'):
            payload['payment_date'] = extra['payment_date']
        return self._make_request('payment_received', payload, employee_id, employee_token)
    
    def poll_commands(self):
        """Получение команд из очереди сервера."""
        try:
            response = requests.get(
                self.api_url,
                params={
                    'api_token': self.api_token,
                    'deviceId': self.device_id,
                    'markDelivered': '1'
                },
                timeout=15
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {'ok': False, 'error': f'HTTP {response.status_code}'}
        except requests.exceptions.Timeout:
            return {'ok': False, 'error': 'timeout'}
        except requests.exceptions.ConnectionError:
            return {'ok': False, 'error': 'no_connection'}
        except Exception as e:
            return {'ok': False, 'error': str(e)}
    
    def send_async(self, method_name, *args, callback=None):
        """Асинхронная отправка команды с опциональным callback."""
        def worker():
            try:
                method = getattr(self, method_name)
                result = method(*args)
                if callback:
                    callback(result)
            except Exception as e:
                if callback:
                    callback({'ok': False, 'error': str(e)})
        
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return thread
