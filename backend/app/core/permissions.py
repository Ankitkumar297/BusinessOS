"""Stable permission catalog shared by provisioning and team administration."""

RESOURCE_ACTIONS = {
    "users": ["view", "create", "update", "deactivate", "delete", "assign_roles"],
    "roles": ["view", "create", "update", "delete", "assign_permissions"],
    "customers": ["view", "create", "update", "deactivate", "delete"],
    "products": ["view", "create", "update", "deactivate", "delete", "manage_suppliers"],
    "suppliers": ["view", "create", "update", "deactivate", "delete"],
    "inventory": ["view", "adjust", "manage"], "orders": ["view", "create", "update", "confirm", "cancel"],
    "payments": ["view", "create", "update"], "invoices": ["view", "create"],
    "reports": ["view"], "audit": ["view"], "settings": ["view", "manage"],
}
PERMISSIONS = {f"{resource}.{action}": f"{action.replace('_', ' ').capitalize()} {resource}"
               for resource, actions in RESOURCE_ACTIONS.items() for action in actions}
PERMISSIONS.update({"business.manage": "Manage business settings", "users.read": "View users (legacy)",
                    "users.manage": "Manage users (legacy)", "roles.read": "View roles (legacy)",
                    "roles.manage": "Manage roles (legacy)"})
DEFAULT_ROLES = {
    "Owner": set(PERMISSIONS),
    "Admin": set(PERMISSIONS) - {"business.manage", "settings.manage"},
    "Manager": {code for code in PERMISSIONS if code.endswith(".view") or code.endswith(".read")},
    "Employee": set(),
}
