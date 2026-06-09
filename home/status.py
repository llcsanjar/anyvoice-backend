# backend/status/status.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from datetime import datetime, timezone
from typing import Dict, List
import asyncio
import json
from menu.menu import user_status_collection

router = APIRouter()

# Connection Manager барои статусҳо
class StatusConnectionManager:
    def __init__(self):
        # active_connections: dict[user_id, list[websocket]]
        self.active_connections: Dict[str, list[WebSocket]] = {}
        # user_last_seen: dict[user_id, datetime]
        self.user_last_seen: Dict[str, datetime] = {}
        # Таски пайваста барои тоза кардани пайвастҳои мурда
        self.cleanup_task = None
        # Оғоз кардани таски тозакунӣ
        asyncio.create_task(self.start_cleanup_task())

    async def start_cleanup_task(self):
        """Оғоз кардани таски тозакунии пайвастҳои мурда"""
        while True:
            await asyncio.sleep(60)  # Ҳар 60 сония тоза кун
            await self.cleanup_dead_connections()

    async def cleanup_dead_connections(self):
        """Тоза кардани пайвастҳои мурда"""
        now = datetime.now(timezone.utc)
        to_remove = []
        
        for user_id, connections in self.active_connections.items():
            active_conns = []
            for conn in connections:
                try:
                    # Санҷидани пайваст бо фиристодани ping
                    await conn.send_json({"type": "ping"})
                    active_conns.append(conn)
                except:
                    pass  # Пайвасти мурда
            
            if active_conns:
                self.active_connections[user_id] = active_conns
            else:
                to_remove.append(user_id)
        
        # Тоза кардани корбароне ки пайваст надоранд
        for user_id in to_remove:
            if user_id in self.active_connections:
                del self.active_connections[user_id]
                self.user_last_seen[user_id] = now
                await self.update_user_status(user_id, False)
                await self.broadcast_status_change(user_id, False)
                print(f"User {user_id} cleaned up (no connections)")

    async def connect(self, websocket: WebSocket, user_id: str):
        try:
            await websocket.accept()
            if user_id not in self.active_connections:
                self.active_connections[user_id] = []
            self.active_connections[user_id].append(websocket)
            
            # Навсозии вақти охирин дида шуд
            self.user_last_seen[user_id] = datetime.now(timezone.utc)
            
            # Навсозии статус дар MongoDB
            await self.update_user_status(user_id, True)
            
            # Ба ҳама пахн кун, ки ин корбар онлайн шуд
            await self.broadcast_status_change(user_id, True)
            
            print(f"User {user_id} connected. Total online: {len(self.active_connections)}")
            return True
        except Exception as e:
            print(f"Error in status connect: {e}")
            return False

    def disconnect(self, websocket: WebSocket, user_id: str):
        try:
            if user_id in self.active_connections:
                if websocket in self.active_connections[user_id]:
                    self.active_connections[user_id].remove(websocket)
                
                # Агар дигар пайваст набошад, корбарро офлайн кун
                if not self.active_connections[user_id]:
                    del self.active_connections[user_id]
                    
                    # Навсозии вақти охирин дида шуд
                    self.user_last_seen[user_id] = datetime.now(timezone.utc)
                    
                    # Навсозии статус дар MongoDB (офлайн)
                    asyncio.create_task(self.update_user_status(user_id, False))
                    
                    # Ба ҳама пахн кун, ки ин корбар офлайн шуд
                    asyncio.create_task(self.broadcast_status_change(user_id, False))
                    
                    print(f"User {user_id} disconnected. Total online: {len(self.active_connections)}")
        except Exception as e:
            print(f"Error in status disconnect: {e}")

    async def update_user_status(self, user_id: str, is_online: bool):
        """Навсозии статуси корбар дар MongoDB"""
        try:
            now = datetime.now(timezone.utc)
            user_status_collection.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "user_id": user_id,
                        "is_online": is_online,
                        "last_seen": now,
                        "updated_at": now
                    }
                },
                upsert=True
            )
        except Exception as e:
            print(f"Error updating user status: {e}")

    async def get_user_status(self, user_id: str) -> dict:
        """Гирифтани статуси корбар аз MongoDB"""
        try:
            # Аввал аз хотираи фаврӣ санҷед
            if user_id in self.active_connections and self.active_connections[user_id]:
                return {
                    "user_id": user_id,
                    "is_online": True,
                    "last_seen": datetime.now(timezone.utc).isoformat() + "Z"
                }
            
            # Агар дар хотира набошад, аз MongoDB гир
            status = user_status_collection.find_one({"user_id": user_id})
            if status:
                return {
                    "user_id": status["user_id"],
                    "is_online": status.get("is_online", False),
                    "last_seen": status.get("last_seen").isoformat() + "Z" if status.get("last_seen").isoformat() + "Z" else None
                }
            else:
                return {
                    "user_id": user_id,
                    "is_online": False,
                    "last_seen": None
                }
        except Exception as e:
            print(f"Error getting user status: {e}")
            return {
                "user_id": user_id,
                "is_online": False,
                "last_seen": None
            }

    async def broadcast_status_change(self, user_id: str, is_online: bool):
        """Пахн кардани тағйироти статус ба ҳамаи корбарони пайваст"""
        try:
            # Тайёр кардани паём
            message = {
                "type": "user_status_change",
                "user_id": user_id,
                "is_online": is_online,
                "last_seen": datetime.now(timezone.utc).isoformat() + "Z"
            }
            
            # Ба ҳамаи пайвастҳо пахн кун
            for uid, connections in list(self.active_connections.items()):
                for connection in connections[:]:  # Нусхаи рӯйхат барои тағйирот
                    try:
                        await connection.send_json(message)
                    except:
                        # Агар пайваст корношоям бошад, онро тоза кун
                        try:
                            self.disconnect(connection, uid)
                        except:
                            pass
        except Exception as e:
            print(f"Error broadcasting status change: {e}")

    async def get_multiple_users_status(self, user_ids: List[str]) -> dict:
        """Гирифтани статуси якчанд корбар дар як вақт"""
        try:
            statuses = {}
            for user_id in user_ids:
                # Аввал аз хотираи фаврӣ санҷед
                if user_id in self.active_connections and self.active_connections[user_id]:
                    statuses[user_id] = {
                        "is_online": True,
                        "last_seen": datetime.now(timezone.utc).isoformat() + "Z"
                    }
                else:
                    # Агар дар хотира набошад, аз MongoDB гир
                    status = user_status_collection.find_one({"user_id": user_id})
                    if status:
                        statuses[user_id] = {
                            "is_online": status.get("is_online", False),
                            "last_seen": status.get("last_seen").isoformat() + "Z" if status.get("last_seen").isoformat() + "Z" else None
                        }
                    else:
                        statuses[user_id] = {
                            "is_online": False,
                            "last_seen": None
                        }
            return statuses
        except Exception as e:
            print(f"Error getting multiple users status: {e}")
            return {user_id: {"is_online": False, "last_seen": None} for user_id in user_ids}

    async def is_user_online(self, user_id: str) -> bool:
        """Санҷидани онлайн будани корбар"""
        return user_id in self.active_connections and bool(self.active_connections[user_id])

# Сохтани менедҷери статус
status_manager = StatusConnectionManager()

# WebSocket барои статус
@router.websocket("/ws/status/{user_id}")
async def websocket_status(websocket: WebSocket, user_id: str):
    connected = await status_manager.connect(websocket, user_id)
    if not connected:
        return
    
    try:
        while True:
            # Интро барои нигоҳ доштани пайваст
            data = await websocket.receive_text()
            # Агар дастури махсус бошад, иҷро кун
            try:
                message = json.loads(data)
                if message.get("type") == "ping":
                    # Ҷавоб ба ping барои нигоҳ доштани пайваст
                    await websocket.send_json({"type": "pong"})
                elif message.get("type") == "get_status":
                    # Дархости статуси корбари дигар
                    target_user_id = message.get("target_user_id")
                    if target_user_id:
                        status = await status_manager.get_user_status(target_user_id)
                        await websocket.send_json({
                            "type": "user_status_response",
                            "user_id": target_user_id,
                            "status": status
                        })
            except json.JSONDecodeError:
                # Агар json набошад, ҳамчун ping ҳисоб кун
                await websocket.send_json({"type": "pong"})
            except Exception as e:
                print(f"Error processing message: {e}")
    except WebSocketDisconnect:
        status_manager.disconnect(websocket, user_id)
    except Exception as e:
        print(f"Error in status websocket: {e}")
        status_manager.disconnect(websocket, user_id)

# API барои гирифтани статуси корбар
@router.get("/api/status/{user_id}")
async def get_user_status(user_id: str):
    """Гирифтани статуси корбар"""
    status = await status_manager.get_user_status(user_id)
    return status

# API барои гирифтани статуси якчанд корбар
@router.post("/api/status/multiple")
async def get_multiple_users_status(user_ids: List[str]):
    """Гирифтани статуси якчанд корбар"""
    statuses = await status_manager.get_multiple_users_status(user_ids)
    return statuses

# API барои санҷидани онлайн будани корбар
@router.get("/api/is-online/{user_id}")
async def is_user_online(user_id: str):
    """Санҷидани онлайн будани корбар"""
    is_online = await status_manager.is_user_online(user_id)
    return {"user_id": user_id, "is_online": is_online}
