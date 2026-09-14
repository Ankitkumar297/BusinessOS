import { Navigate, Outlet, RouterProvider, createBrowserRouter } from "react-router-dom";
import { AppLayout } from "../layouts/app-layout";
import { useAuth } from "../features/auth/use-auth";
import { DashboardPage } from "../pages/dashboard-page";
import { LoginPage, RegisterPage } from "../pages/auth-pages";
import { UsersPage } from "../features/team/users-page";
import { RolesPage } from "../features/team/roles-page";
import { PermissionRoute } from "../features/team/permissions";
import { CustomerDetailsPage, CustomerEditorPage, CustomersPage } from "../features/customers/customers-pages";
import { SupplierDetails, SupplierEditor, SuppliersPage } from "../features/suppliers/suppliers-page";
import { ProductDetails, ProductEditor, ProductsPage } from "../features/products/products-page";
import { InventoryDetailsPage, InventoryPage } from "../features/inventory/inventory-page";
import { OrderDetails, OrderEditor, OrdersPage } from "../features/orders/orders-page";
import { PaymentDetails, PaymentEditor, PaymentsPage } from "../features/payments/payments-page";
import { InvoiceDetails, InvoiceGenerator, InvoicesPage } from "../features/invoices/invoices-page";
import { ReportsPage } from "../features/reports/reports-page";
import { CustomerStatementPage } from "../features/customer-statements/customer-statement-page";
import { AuditLogsPage } from "../features/audit-logs/audit-logs-page";

function ProtectedRoute(): JSX.Element { const { session, isLoading } = useAuth(); if (isLoading) return <div className="grid min-h-screen place-items-center text-sm text-[#6B7280]">Loading workspace…</div>; return session ? <Outlet /> : <Navigate to="/login" replace />; }

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
  { element: <ProtectedRoute />, children: [
    { element: <AppLayout />, children: [
      { index: true, element: <DashboardPage /> },
      { element: <PermissionRoute permission="reports.view" />, children: [{ path: "reports", element: <ReportsPage /> }] },
      { element: <PermissionRoute permission="reports.view" />, children: [{ path: "customers/:customerId/statement", element: <CustomerStatementPage /> }] },
      { element: <PermissionRoute permission="users.view" />, children: [{ path: "users", element: <UsersPage /> }] },
      { element: <PermissionRoute permission="roles.view" />, children: [{ path: "roles", element: <RolesPage /> }] },
      { element: <PermissionRoute permission="customers.view" />, children: [{ path: "customers", element: <CustomersPage /> }, { path: "customers/:customerId", element: <CustomerDetailsPage /> }] },
      { element: <PermissionRoute permission="customers.create" />, children: [{ path: "customers/new", element: <CustomerEditorPage /> }] },
      { element: <PermissionRoute permission="customers.update" />, children: [{ path: "customers/:customerId/edit", element: <CustomerEditorPage /> }] },
      { element: <PermissionRoute permission="suppliers.view" />, children: [{ path: "suppliers", element: <SuppliersPage /> }, { path: "suppliers/:supplierId", element: <SupplierDetails /> }] },
      { element: <PermissionRoute permission="suppliers.create" />, children: [{ path: "suppliers/new", element: <SupplierEditor /> }] },
      { element: <PermissionRoute permission="suppliers.update" />, children: [{ path: "suppliers/:supplierId/edit", element: <SupplierEditor /> }] },
      { element: <PermissionRoute permission="products.view" />, children: [{ path: "products", element: <ProductsPage /> }, { path: "products/:productId", element: <ProductDetails /> }] },
      { element: <PermissionRoute permission="products.create" />, children: [{ path: "products/new", element: <ProductEditor /> }] },
      { element: <PermissionRoute permission="products.update" />, children: [{ path: "products/:productId/edit", element: <ProductEditor /> }] },
      { element: <PermissionRoute permission="inventory.view" />, children: [{ path: "inventory", element: <InventoryPage /> }, { path: "inventory/:productId", element: <InventoryDetailsPage /> }] },
      { element: <PermissionRoute permission="orders.view" />, children: [{ path: "orders", element: <OrdersPage /> }, { path: "orders/:orderId", element: <OrderDetails /> }] },
      { element: <PermissionRoute permission="orders.create" />, children: [{ path: "orders/new", element: <OrderEditor /> }] },
      { element: <PermissionRoute permission="orders.update" />, children: [{ path: "orders/:orderId/edit", element: <OrderEditor /> }] },
      { element: <PermissionRoute permission="payments.view" />, children: [{ path: "payments", element: <PaymentsPage /> }, { path: "payments/:paymentId", element: <PaymentDetails /> }] },
      { element: <PermissionRoute permission="payments.create" />, children: [{ path: "payments/new", element: <PaymentEditor /> }] },
      { element: <PermissionRoute permission="invoices.view" />, children: [{ path: "invoices", element: <InvoicesPage /> }, { path: "invoices/:invoiceId", element: <InvoiceDetails /> }] },
      { element: <PermissionRoute permission="invoices.create" />, children: [{ path: "invoices/new", element: <InvoiceGenerator /> }] },
      { element: <PermissionRoute permission="audit.view" />, children: [{ path: "audit-logs", element: <AuditLogsPage /> }] },
    ] },
  ] },
  { path: "*", element: <Navigate to="/" replace /> },
]);

export function AppRouter(): JSX.Element { return <RouterProvider router={router} />; }
