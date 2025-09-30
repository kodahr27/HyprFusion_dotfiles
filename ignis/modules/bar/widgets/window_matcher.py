from typing import List, Dict, Any, Optional
from ignis.services.applications import Application


class WindowMatcher:
    """Shared window matching logic for taskbar modules"""
    
    @staticmethod
    def normalize_string(text: str) -> str:
        """Normalize string for comparison"""
        return (text or "").strip().lower()
    
    @staticmethod
    def normalize_app_id(app_id: str) -> str:
        """Normalize app ID for comparison - keeps full ID to distinguish webapps"""
        return WindowMatcher.normalize_string(app_id)
    
    @classmethod
    def matches_window_to_app(cls, window: Any, app: Application) -> bool:
        """
        Check if a window matches an application
        Uses comprehensive matching logic combining both approaches
        """
        if not window or not app:
            return False
        
        app_id_norm = cls.normalize_app_id(app.id)
        app_name_norm = cls.normalize_string(app.name)
        
        # Get window properties
        initial_title = cls.normalize_string(getattr(window, "initial_title", "") or getattr(window, "initialTitle", ""))
        initial_class = cls.normalize_string(getattr(window, "initial_class", ""))
        window_class = cls.normalize_string(getattr(window, "class", "") or getattr(window, "class_name", ""))
        window_app_id = cls.normalize_string(getattr(window, "app_id", ""))
        window_title = cls.normalize_string(getattr(window, "title", ""))
        
        # Priority 1: Exact match by initial title with app name
        if initial_title and app_name_norm and initial_title == app_name_norm:
            return True
        
        # Priority 2: Exact match by app_id
        if window_app_id and window_app_id == app_id_norm:
            return True
        
        # Priority 3: Exact match by initial_class
        if initial_class and initial_class == app_id_norm:
            return True
        
        # Priority 4: Exact match by window class
        if window_class and window_class == app_id_norm:
            return True
        
        # Priority 5: Substring match for app name in window title (fallback)
        if window_title and app_name_norm and app_name_norm in window_title:
            return True
        
        # Priority 6: Partial match for app_id in class fields (for compatibility)
        if app_id_norm:
            if window_class and app_id_norm in window_class:
                return True
            if initial_class and app_id_norm in initial_class:
                return True
        
        return False
    
    @classmethod
    def group_windows_by_app(cls, windows: List[Any], applications_service) -> Dict[str, Dict]:
        """
        Group windows by their matching applications
        Returns dict with group_key -> {app, windows, icon}
        """
        from .icon_manager import IconManager
        
        running_groups = {}
        
        for window in windows:
            # Get window identifiers
            initial_title = cls.normalize_string(getattr(window, "initial_title", "") or getattr(window, "initialTitle", ""))
            current_title = cls.normalize_string(getattr(window, "title", ""))
            class_name = cls.normalize_string(getattr(window, "class_name", "") or getattr(window, "initial_class", ""))
            
            # Find matching application
            app = cls._find_matching_app(window, applications_service)
            if not app:
                continue
            
            # Create a smart group key that distinguishes different window types of the same app
            group_key = cls._create_group_key(window, app, initial_title, current_title, class_name)
            
            # Get icon (try to find override from desktop file)
            icon_override = None
            if initial_title:
                desktop_file = IconManager.find_desktop_file_by_name(initial_title)
                if desktop_file:
                    icon_override = IconManager.find_icon_for_desktop(desktop_file)
            
            # Use app icon if no override found
            if not icon_override:
                icon_override = app.icon
            
            # Add to groups
            if group_key not in running_groups:
                running_groups[group_key] = {
                    "app": app,
                    "windows": [],
                    "icon": icon_override
                }
            
            running_groups[group_key]["windows"].append(window)
            
            # Update icon if current group has no icon
            if running_groups[group_key]["icon"] is None:
                running_groups[group_key]["icon"] = icon_override
        
        return running_groups
    
    @classmethod
    def _create_group_key(cls, window: Any, app: Application, initial_title: str, current_title: str, class_name: str) -> str:
        """
        Create a group key that intelligently separates different window types
        without hardcoding specific patterns
        """
        # Strategy: Use the most specific identifier available
        app_name_norm = cls.normalize_string(app.name)
        
        if initial_title:
            if initial_title != app_name_norm and initial_title not in app_name_norm and app_name_norm not in initial_title:
                return f"{app.id}:{initial_title}"
        
        if current_title and initial_title and current_title != initial_title:
            if len(current_title) > 10 and current_title not in initial_title:
                return f"{app.id}:{current_title}"
        
        if initial_title and (initial_title == app_name_norm or app_name_norm in initial_title):
            return f"{app.id}:main"
        
        return app.id
    
    @classmethod
    def should_windows_be_grouped_together(cls, window1: Any, window2: Any, app: Application) -> bool:
        """
        Determine if two windows of the same app should be grouped together
        """
        if not window1 or not window2 or not app:
            return False
        
        # Get titles for both windows
        title1_initial = cls.normalize_string(getattr(window1, "initial_title", "") or getattr(window1, "initialTitle", ""))
        title1_current = cls.normalize_string(getattr(window1, "title", ""))
        title2_initial = cls.normalize_string(getattr(window2, "initial_title", "") or getattr(window2, "initialTitle", ""))
        title2_current = cls.normalize_string(getattr(window2, "title", ""))
        
        # Create group keys for both windows
        key1 = cls._create_group_key(window1, app, title1_initial, title1_current, "")
        key2 = cls._create_group_key(window2, app, title2_initial, title2_current, "")
        
        return key1 == key2
    
    @classmethod
    def _find_matching_app(cls, window: Any, applications_service) -> Optional[Application]:
        """Find the application that matches a window"""
        initial_title = getattr(window, "initial_title", "") or getattr(window, "initialTitle", "")
        class_name = getattr(window, "class_name", "") or getattr(window, "initial_class", "")
        
        if initial_title:
            app = cls._get_app_by_title(initial_title.strip(), applications_service)
            if app:
                return app
        
        if class_name:
            app = cls._get_app_by_class(class_name.strip(), applications_service)
            if app:
                return app
        
        return None
    
    @classmethod
    def _get_app_by_class(cls, class_name: str, applications_service) -> Optional[Application]:
        """Find app by class name with smart matching priority"""
        if not class_name:
            return None
        
        class_name_lc = class_name.lower()
        
        exact_matches = []
        substring_matches = []
        
        for app in applications_service.apps:
            app_id_lc = app.id.lower() if app.id else ""
            if not app_id_lc:
                continue
                
            app_id_base = app_id_lc.replace('.desktop', '')
            if app_id_base == class_name_lc or app_id_lc == class_name_lc:
                exact_matches.append(app)
            elif class_name_lc in app_id_lc:
                substring_matches.append(app)
        
        if exact_matches:
            return min(exact_matches, key=lambda app: len(app.id))
        
        if substring_matches:
            return min(substring_matches, key=lambda app: len(app.id))
        
        return None
    
    @classmethod
    def _get_app_by_title(cls, title: str, applications_service) -> Optional[Application]:
        """Find app by title"""
        if not title:
            return None
        
        title_lc = title.lower()
        for app in applications_service.apps:
            app_name_lc = app.name.lower() if app.name else ""
            if app_name_lc and app_name_lc == title_lc:
                return app
        return None
