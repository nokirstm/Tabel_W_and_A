# -*- coding: utf-8 -*-
"""Сетевой клиент синхронизации.
ЗЕРКАЛО: core/sync_client.py и android/sync_client.py обязаны совпадать байт-в-байт."""
import os
import uuid
import threading
import requests


class SyncClient:
    def __init__(self, api_url, api_token, device_id_file):
        self.api_url = api_url
        self.api_token = api_token
        self.device_id_file = device_id_file
        self.device_id = self._load_or_create_device_id()
        self.employee_id = ""
        self.employee_token = ""

    def _load_or_create_device_id(self):
        try:
            if os.path.exists(self.device_id_file):
                with open(self.device_id_file, "r", encoding="utf-8") as f:
                    did = f.read().strip()
                if did:
                    return did
        except Exception:
            pass
        did = str(uuid.uuid4())
        try:
            with open(self.device_id_file, "w", encoding="utf-8") as f:
                f.write(did)
        except Exception:
            pass
        return did

    def set_credentials(self, employee_id, employee_token):
        self.employee_id = str(employee_id or "")
        self.employee_token = str(employee_token or "")

    def _make_request(self, command, payload=None, employee_id=None, employee_token=None):
        data = {
            "api_token": self.api_token,
            "command": command,
            "device_id": self.device_id,
            "request_id": str(uuid.uuid4()),
            "payload": payload or {},
        }
        if employee_id:
            data["employee_id"] = employee_id
        if employee_token:
            data["employee_token"] = employee_token
        # Повтор при таймауте: холодный старт Apps Script после публикации
        # может греться дольше 15 секунд. Для опроса очереди повтор запрещён,
        # чтобы два опроса не наложились и не пометили команды дважды.
        attempts = 1 if command == "poll_commands" else 2
        last = {"ok": False, "error": "timeout"}
        for _ in range(attempts):
            try:
                resp = requests.post(self.api_url, json=data, timeout=15)
                return resp.json()
            except requests.exceptions.Timeout:
                last = {"ok": False, "error": "timeout"}
            except requests.exceptions.ConnectionError:
                return {"ok": False, "error": "no_connection"}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        return last

    def _get_queue(self):
        try:
            resp = requests.get(
                self.api_url,
                params={"api_token": self.api_token,
                        "deviceId": self.device_id,
                        "markDelivered": "1"},
                timeout=15)
            return resp.json()
        except requests.exceptions.Timeout:
            return {"ok": False, "error": "timeout"}
        except requests.exceptions.ConnectionError:
            return {"ok": False, "error": "no_connection"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    def send_async(self, method_name, *args, callback=None):
        def worker():
            try:
                if method_name == "create_account":
                    res = self._make_request("create_account", {"name": args[0], "birth_date": args[1]})
                elif method_name == "create_manager":
                    res = self._make_request("create_manager", {"name": args[0], "birth_date": args[1]})
                elif method_name == "create_employee":
                    res = self._make_request("create_employee", {"manager_id": args[0], "manager_token": args[1], "name": args[2], "birth_date": args[3]})
                elif method_name == "list_employees":
                    res = self._make_request("list_employees", {"manager_id": args[0], "manager_token": args[1]})
                elif method_name == "attach_employee":
                    res = self._make_request("attach_employee", {"manager_id": args[0], "manager_token": args[1], "name": args[2], "birth_date": args[3]})
                elif method_name == "bind_device":
                    res = self._make_request("bind_device", {"employee_token": args[0], "name": args[1] if len(args) > 1 else None, "birth_date": args[2] if len(args) > 2 else None})
                elif method_name == "restore_account":
                    res = self._make_request("restore_account", {"name": args[0], "birth_date": args[1], "device_type": args[2] if len(args) > 2 else "android"})
                elif method_name == "day_updated":
                    res = self._make_request("day_updated", {"date": args[2], "entry": args[3], "version": args[4]}, args[0], args[1])
                elif method_name == "day_approved":
                    res = self._make_request("day_approved", {"date": args[2], "version": args[3]}, args[0], args[1])
                elif method_name == "approve_employee_day":
                    res = self._make_request("approve_employee_day", {"manager_id": args[0], "manager_token": args[1], "employee_id": args[2], "date": args[3], "version": args[4]})
                elif method_name == "unlink_windows":
                    res = self._make_request("unlink_windows", {"employee_id": args[0], "employee_token": args[1]})
                elif method_name == "fetch_employee_state":
                    res = self._make_request("fetch_employee_state", {"manager_id": args[0], "manager_token": args[1], "employee_id": args[2]})
                elif method_name == "archive_employee":
                    res = self._make_request("archive_employee", {"manager_id": args[0], "manager_token": args[1], "employee_id": args[2]})
                elif method_name == "list_archived_employees":
                    res = self._make_request("list_archived_employees", {"manager_id": args[0], "manager_token": args[1]})
                elif method_name == "payment_date_entered":
                    res = self._make_request("payment_date_entered", {"week_id": args[2], "payment_date": args[3], "version": args[4]}, args[0], args[1])
                elif method_name == "payment_received":
                    res = self._make_request("payment_received", {"week_id": args[2], "payment_date": args[3], "payment_confirmed": True, "version": args[4]}, args[0], args[1])
                elif method_name == "poll_commands":
                    res = self._get_queue()
                else:
                    res = {"ok": False, "error": "unknown_command"}
                if callback:
                    callback(res)
            except Exception as e:
                if callback:
                    callback({"ok": False, "error": str(e)})

        threading.Thread(target=worker, daemon=True).start()
