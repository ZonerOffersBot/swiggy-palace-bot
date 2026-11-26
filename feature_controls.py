"""Digital shop feature switch registry. Switches are persisted in PostgreSQL."""
FEATURES = [
  {
    "key": "dashboard_analytics_overview",
    "group": "Dashboard & Analytics",
    "label": "Overview"
  },
  {
    "key": "dashboard_analytics_live_activity",
    "group": "Dashboard & Analytics",
    "label": "Live activity"
  },
  {
    "key": "dashboard_analytics_revenue_analytics",
    "group": "Dashboard & Analytics",
    "label": "Revenue analytics"
  },
  {
    "key": "dashboard_analytics_sales_by_product",
    "group": "Dashboard & Analytics",
    "label": "Sales by product"
  },
  {
    "key": "dashboard_analytics_sales_by_category",
    "group": "Dashboard & Analytics",
    "label": "Sales by category"
  },
  {
    "key": "dashboard_analytics_order_analytics",
    "group": "Dashboard & Analytics",
    "label": "Order analytics"
  },
  {
    "key": "dashboard_analytics_conversion_analytics",
    "group": "Dashboard & Analytics",
    "label": "Conversion analytics"
  },
  {
    "key": "dashboard_analytics_customer_growth",
    "group": "Dashboard & Analytics",
    "label": "Customer growth"
  },
  {
    "key": "dashboard_analytics_top_customers",
    "group": "Dashboard & Analytics",
    "label": "Top customers"
  },
  {
    "key": "dashboard_analytics_low_stock_alerts",
    "group": "Dashboard & Analytics",
    "label": "Low-stock alerts"
  },
  {
    "key": "products_digital_inventory_product_catalogue",
    "group": "Products & Digital Inventory",
    "label": "Product catalogue"
  },
  {
    "key": "products_digital_inventory_add_digital_product",
    "group": "Products & Digital Inventory",
    "label": "Add digital product"
  },
  {
    "key": "products_digital_inventory_edit_product",
    "group": "Products & Digital Inventory",
    "label": "Edit product"
  },
  {
    "key": "products_digital_inventory_delete_product_soft_disable",
    "group": "Products & Digital Inventory",
    "label": "Delete product (soft disable)"
  },
  {
    "key": "products_digital_inventory_product_categories",
    "group": "Products & Digital Inventory",
    "label": "Product categories"
  },
  {
    "key": "products_digital_inventory_category_pricing",
    "group": "Products & Digital Inventory",
    "label": "Category pricing"
  },
  {
    "key": "products_digital_inventory_product_pricing",
    "group": "Products & Digital Inventory",
    "label": "Product pricing"
  },
  {
    "key": "products_digital_inventory_product_availability",
    "group": "Products & Digital Inventory",
    "label": "Product availability"
  },
  {
    "key": "products_digital_inventory_digital_file_upload",
    "group": "Products & Digital Inventory",
    "label": "Digital file upload"
  },
  {
    "key": "products_digital_inventory_text_product_editor",
    "group": "Products & Digital Inventory",
    "label": "Text product editor"
  },
  {
    "key": "products_digital_inventory_bulk_product_import",
    "group": "Products & Digital Inventory",
    "label": "Bulk product import"
  },
  {
    "key": "products_digital_inventory_inventory_stock_monitor",
    "group": "Products & Digital Inventory",
    "label": "Inventory stock monitor"
  },
  {
    "key": "orders_delivery_all_orders",
    "group": "Orders & Delivery",
    "label": "All orders"
  },
  {
    "key": "orders_delivery_order_search",
    "group": "Orders & Delivery",
    "label": "Order search"
  },
  {
    "key": "orders_delivery_order_details",
    "group": "Orders & Delivery",
    "label": "Order details"
  },
  {
    "key": "orders_delivery_pending_orders",
    "group": "Orders & Delivery",
    "label": "Pending orders"
  },
  {
    "key": "orders_delivery_paid_orders",
    "group": "Orders & Delivery",
    "label": "Paid orders"
  },
  {
    "key": "orders_delivery_failed_orders",
    "group": "Orders & Delivery",
    "label": "Failed orders"
  },
  {
    "key": "orders_delivery_cancelled_orders",
    "group": "Orders & Delivery",
    "label": "Cancelled orders"
  },
  {
    "key": "orders_delivery_refunded_orders",
    "group": "Orders & Delivery",
    "label": "Refunded orders"
  },
  {
    "key": "orders_delivery_manual_delivery_retry",
    "group": "Orders & Delivery",
    "label": "Manual delivery retry"
  },
  {
    "key": "orders_delivery_delivery_history",
    "group": "Orders & Delivery",
    "label": "Delivery history"
  },
  {
    "key": "orders_delivery_resend_digital_product",
    "group": "Orders & Delivery",
    "label": "Resend digital product"
  },
  {
    "key": "orders_delivery_delivery_failure_alerts",
    "group": "Orders & Delivery",
    "label": "Delivery failure alerts"
  },
  {
    "key": "payments_wallet_payment_settings",
    "group": "Payments & Wallet",
    "label": "Payment settings"
  },
  {
    "key": "payments_wallet_wallet_master_switch",
    "group": "Payments & Wallet",
    "label": "Wallet master switch"
  },
  {
    "key": "payments_wallet_wallet_balance_lookup",
    "group": "Payments & Wallet",
    "label": "Wallet balance lookup"
  },
  {
    "key": "payments_wallet_wallet_transaction_history",
    "group": "Payments & Wallet",
    "label": "Wallet transaction history"
  },
  {
    "key": "payments_wallet_deposit_requests",
    "group": "Payments & Wallet",
    "label": "Deposit requests"
  },
  {
    "key": "payments_wallet_approve_deposits",
    "group": "Payments & Wallet",
    "label": "Approve deposits"
  },
  {
    "key": "payments_wallet_reject_deposits",
    "group": "Payments & Wallet",
    "label": "Reject deposits"
  },
  {
    "key": "payments_wallet_payment_gateway_status",
    "group": "Payments & Wallet",
    "label": "Payment gateway status"
  },
  {
    "key": "payments_wallet_payment_reconciliation",
    "group": "Payments & Wallet",
    "label": "Payment reconciliation"
  },
  {
    "key": "payments_wallet_refund_management",
    "group": "Payments & Wallet",
    "label": "Refund management"
  },
  {
    "key": "customers_users_customer_directory",
    "group": "Customers & Users",
    "label": "Customer directory"
  },
  {
    "key": "customers_users_customer_profile",
    "group": "Customers & Users",
    "label": "Customer profile"
  },
  {
    "key": "customers_users_customer_purchase_history",
    "group": "Customers & Users",
    "label": "Customer purchase history"
  },
  {
    "key": "customers_users_customer_wallet_view",
    "group": "Customers & Users",
    "label": "Customer wallet view"
  },
  {
    "key": "customers_users_block_customer",
    "group": "Customers & Users",
    "label": "Block customer"
  },
  {
    "key": "customers_users_unblock_customer",
    "group": "Customers & Users",
    "label": "Unblock customer"
  },
  {
    "key": "customers_users_customer_notes",
    "group": "Customers & Users",
    "label": "Customer notes"
  },
  {
    "key": "customers_users_customer_notifications",
    "group": "Customers & Users",
    "label": "Customer notifications"
  },
  {
    "key": "coupons_marketing_coupon_manager",
    "group": "Coupons & Marketing",
    "label": "Coupon manager"
  },
  {
    "key": "coupons_marketing_create_coupon",
    "group": "Coupons & Marketing",
    "label": "Create coupon"
  },
  {
    "key": "coupons_marketing_edit_coupon",
    "group": "Coupons & Marketing",
    "label": "Edit coupon"
  },
  {
    "key": "coupons_marketing_disable_coupon",
    "group": "Coupons & Marketing",
    "label": "Disable coupon"
  },
  {
    "key": "coupons_marketing_coupon_usage_analytics",
    "group": "Coupons & Marketing",
    "label": "Coupon usage analytics"
  },
  {
    "key": "coupons_marketing_discount_campaigns",
    "group": "Coupons & Marketing",
    "label": "Discount campaigns"
  },
  {
    "key": "coupons_marketing_featured_products",
    "group": "Coupons & Marketing",
    "label": "Featured products"
  },
  {
    "key": "coupons_marketing_announcement_banners",
    "group": "Coupons & Marketing",
    "label": "Announcement banners"
  },
  {
    "key": "support_notifications_support_inbox",
    "group": "Support & Notifications",
    "label": "Support inbox"
  },
  {
    "key": "support_notifications_reply_to_support",
    "group": "Support & Notifications",
    "label": "Reply to support"
  },
  {
    "key": "support_notifications_close_support_ticket",
    "group": "Support & Notifications",
    "label": "Close support ticket"
  },
  {
    "key": "support_notifications_reopen_support_ticket",
    "group": "Support & Notifications",
    "label": "Reopen support ticket"
  },
  {
    "key": "support_notifications_broadcast_message",
    "group": "Support & Notifications",
    "label": "Broadcast message"
  },
  {
    "key": "support_notifications_scheduled_announcements",
    "group": "Support & Notifications",
    "label": "Scheduled announcements"
  },
  {
    "key": "support_notifications_delivery_notifications",
    "group": "Support & Notifications",
    "label": "Delivery notifications"
  },
  {
    "key": "support_notifications_admin_alerts",
    "group": "Support & Notifications",
    "label": "Admin alerts"
  },
  {
    "key": "admin_roles_permissions_admin_directory",
    "group": "Admin Roles & Permissions",
    "label": "Admin directory"
  },
  {
    "key": "admin_roles_permissions_add_admin",
    "group": "Admin Roles & Permissions",
    "label": "Add admin"
  },
  {
    "key": "admin_roles_permissions_remove_admin",
    "group": "Admin Roles & Permissions",
    "label": "Remove admin"
  },
  {
    "key": "admin_roles_permissions_role_management",
    "group": "Admin Roles & Permissions",
    "label": "Role management"
  },
  {
    "key": "admin_roles_permissions_permission_matrix",
    "group": "Admin Roles & Permissions",
    "label": "Permission matrix"
  },
  {
    "key": "reports_exports_sales_report",
    "group": "Reports & Exports",
    "label": "Sales report"
  },
  {
    "key": "reports_exports_orders_csv_export",
    "group": "Reports & Exports",
    "label": "Orders CSV export"
  },
  {
    "key": "reports_exports_products_csv_export",
    "group": "Reports & Exports",
    "label": "Products CSV export"
  },
  {
    "key": "reports_exports_customer_csv_export",
    "group": "Reports & Exports",
    "label": "Customer CSV export"
  },
  {
    "key": "security_backup_system_health_master_shop_emergency_switch",
    "group": "Security, Backup & System Health",
    "label": "Master shop emergency switch"
  },
  {
    "key": "security_backup_system_health_feature_switchboard",
    "group": "Security, Backup & System Health",
    "label": "Feature switchboard"
  },
  {
    "key": "security_backup_system_health_admin_audit_log",
    "group": "Security, Backup & System Health",
    "label": "Admin audit log"
  }
]
FEATURE_KEYS = {item["key"] for item in FEATURES}
MASTER_KEY = "security_system_health_master_shop_emergency_switch"
