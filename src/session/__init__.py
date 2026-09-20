"""Streamlit session helpers."""

from __future__ import annotations

from dataclasses import dataclass, field

from src.context.state import AnalyticalState
from src.ingestion.registry import Dataset
from src.matching.relationships import RelationshipCandidate, find_relationships
from src.profiling.schema import TableProfile, profile_dataset


DATASETS_KEY = "datasets"
PROFILES_KEY = "profiles"
RELATIONSHIPS_KEY = "relationships"
STATE_KEY = "analytical_state"
HISTORY_KEY = "qa_history"
BYTES_KEY = "session_bytes"


@dataclass
class SessionData:
    """Represents the complete in-memory session state for the Streamlit app."""
    datasets: list[Dataset] = field(default_factory=list)
    profiles: list[TableProfile] = field(default_factory=list)
    relationships: list[RelationshipCandidate] = field(default_factory=list)
    state: AnalyticalState = field(default_factory=AnalyticalState)
    history: list[dict] = field(default_factory=list)
    session_bytes: int = 0


def empty_session() -> SessionData:
    """Create a fresh, empty session state."""
    return SessionData()


def add_datasets(session: SessionData, datasets: list[Dataset]) -> SessionData:
    """Add new datasets to the session, refreshing schema profiles and join candidates.

    Args:
        session: Existing SessionData instance.
        datasets: Newly uploaded Dataset objects.

    Returns:
        Updated SessionData with recalculated profiles, relationships, and byte counts.
    """
    combined = list(session.datasets) + list(datasets)
    # Re-profile all combined datasets to account for newly added tables
    profiles = [profile_dataset(item) for item in combined]
    # Detect candidate cross-table join keys across all datasets
    relationships = find_relationships(combined, profiles)
    session_bytes = session.session_bytes + sum(item.meta.size_bytes for item in datasets)
    return SessionData(
        datasets=combined,
        profiles=profiles,
        relationships=relationships,
        state=session.state,
        history=session.history,
        session_bytes=session_bytes,
    )


def load_from_streamlit(st_session) -> SessionData:
    """Extract and deserialize session state from Streamlit session_state.

    Args:
        st_session: streamlit.session_state dictionary-like container.

    Returns:
        SessionData object populated from Streamlit storage.
    """
    return SessionData(
        datasets=list(st_session.get(DATASETS_KEY, [])),
        profiles=list(st_session.get(PROFILES_KEY, [])),
        relationships=list(st_session.get(RELATIONSHIPS_KEY, [])),
        state=AnalyticalState.from_dict(st_session.get(STATE_KEY)),
        history=list(st_session.get(HISTORY_KEY, [])),
        session_bytes=int(st_session.get(BYTES_KEY, 0)),
    )


def persist_to_streamlit(st_session, session: SessionData) -> None:
    """Persist the active SessionData into Streamlit session_state.

    Args:
        st_session: streamlit.session_state container.
        session: Active SessionData object to persist.
    """
    st_session[DATASETS_KEY] = session.datasets
    st_session[PROFILES_KEY] = session.profiles
    st_session[RELATIONSHIPS_KEY] = session.relationships
    st_session[STATE_KEY] = session.state.to_dict()
    st_session[HISTORY_KEY] = session.history
    st_session[BYTES_KEY] = session.session_bytes

