from typing import Dict, Optional
from stock_data_downloader.websocket_server.SimulationSession import SimulationSession
from stock_data_downloader.models import AppConfig
import logging

logger = logging.getLogger(__name__)

class SimulationManager:
    """
    Manages active simulation sessions for connected clients.
    """
    def __init__(self, app_config: AppConfig):
        self._sessions: Dict[str, SimulationSession] = {}
        self._app_config = app_config

    def create_session(self, client_id: str) -> SimulationSession:
        """Creates a new, isolated simulation session for a client."""
        if client_id in self._sessions:
            logger.warning(f"Session for client {client_id} already exists. Returning existing session.")
            return self._sessions[client_id]
        
        logger.info(f"Creating new simulation session for client {client_id}")
        session = SimulationSession(client_id, self._app_config)
        self._sessions[client_id] = session
        return session

    def get_session(self, client_id: str) -> Optional[SimulationSession]:
        """Retrieves a session by client ID."""
        return self._sessions.get(client_id)

    def destroy_session(self, client_id: str):
        """Destroys a client's simulation session."""
        if client_id in self._sessions:
            logger.info(f"Destroying simulation session for client {client_id}")
            del self._sessions[client_id]
        else:
            logger.warning(f"Could not destroy session for client {client_id}: Session not found.")
