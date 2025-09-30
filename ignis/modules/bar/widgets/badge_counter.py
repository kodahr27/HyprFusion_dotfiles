from typing import Dict, List, Any
from ignis.services.applications import Application

from .window_detector import WindowState


class BadgeInfo:
    """Represents badge information for an app"""
    def __init__(self, app: Application, count: int = 0, windows: List[Any] = None):
        self.app = app
        self.count = count
        self.windows = windows or []
        self.visible = count > 0


class BadgeCounter:
    """
    Dedicated badge counting logic.
    Receives window state from WindowDetector and computes badge counts.
    """
    
    def __init__(self):
        self._cached_badges: Dict[str, BadgeInfo] = {}
        self._last_state_time: float = 0
    
    def compute_badges_for_apps(self, window_state: WindowState, apps: List[Application]) -> Dict[str, BadgeInfo]:
        """
        Compute badge information for a list of applications based on current window state.
        
        Args:
            window_state: Current window state from WindowDetector
            apps: List of applications to compute badges for
            
        Returns:
            Dict mapping app.id -> BadgeInfo
        """
        # Use cached result if state unchanged
        if window_state.last_update_time == self._last_state_time:
            return self._cached_badges.copy()
        
        self._last_state_time = window_state.last_update_time
        badges = {}
        
        for app in apps:
            badge_info = self._compute_badge_for_app(app, window_state)
            badges[app.id] = badge_info
        
        # Update cache
        self._cached_badges = badges.copy()
        return badges
    
    def compute_badge_for_app(self, app: Application, window_state: WindowState) -> BadgeInfo:
        """
        Compute badge information for a single application.
        """
        return self._compute_badge_for_app(app, window_state)
    
    def _compute_badge_for_app(self, app: Application, window_state: WindowState) -> BadgeInfo:
        """Internal method to compute badge for an app"""
        if not app or not window_state.app_groups:
            return BadgeInfo(app, 0, [])
        
        total_count = 0
        all_windows = []
        
        # Look through all app groups to find windows that match this app
        for group_key, group_data in window_state.app_groups.items():
            if group_data["app"].id == app.id:
                windows = group_data["windows"]
                total_count += len(windows)
                all_windows.extend(windows)
        
        return BadgeInfo(app, total_count, all_windows)
    
    def get_app_window_groups(self, app: Application, window_state: WindowState) -> Dict[str, Dict]:
        """
        Get all window groups that belong to a specific app.
        """
        if not app or not window_state.app_groups:
            return {}
        
        app_groups = {}
        for group_key, group_data in window_state.app_groups.items():
            if group_data["app"].id == app.id:
                app_groups[group_key] = group_data
        
        return app_groups
    
    def get_running_apps_badges(self, window_state: WindowState, exclude_pinned: bool = True) -> Dict[str, BadgeInfo]:
        """
        Get badge information for all currently running apps.
        """
        if not window_state.app_groups:
            return {}
        
        badges = {}
        
        for group_key, group_data in window_state.app_groups.items():
            app = group_data["app"]
            
            # Skip pinned apps if requested
            if exclude_pinned and app.is_pinned:
                continue
            
            # If we already have this app, add to its count
            if app.id in badges:
                badges[app.id].count += len(group_data["windows"])
                badges[app.id].windows.extend(group_data["windows"])
            else:
                badges[app.id] = BadgeInfo(
                    app, 
                    len(group_data["windows"]), 
                    group_data["windows"].copy()
                )
        
        # Update visibility
        for badge in badges.values():
            badge.visible = badge.count > 0
        
        return badges
    
    def clear_cache(self):
        """Clear cached badge information"""
        self._cached_badges.clear()
        self._last_state_time = 0


# Global instance
_badge_counter = None


def get_badge_counter() -> BadgeCounter:
    """Get the global badge counter instance"""
    global _badge_counter
    if _badge_counter is None:
        _badge_counter = BadgeCounter()
    return _badge_counter
