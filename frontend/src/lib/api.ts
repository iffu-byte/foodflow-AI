export const API_URL = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
export const WS_URL = API_URL.replace(/^http/, "ws");

export type OrderStatus =
  | "PLACED"
  | "ACCEPTED"
  | "PREPARING"
  | "READY"
  | "PICKED_UP"
  | "DELIVERED"
  | "CANCELLED"
  | "FAILED";

export type RiderStatus =
  | "IDLE"
  | "TO_PICKUP"
  | "TO_DROP"
  | "ON_BREAK"
  | "OFFLINE";

export interface OrderItem {
  menu_item_id: string;
  name: string;
  qty: number;
  unit_price: string;
}

export interface Order {
  id: string;
  customer_id: string;
  restaurant_id: string;
  rider_id: string | null;
  status: OrderStatus;
  placed_at: string;
  promised_eta_at: string | null;
  deadline_at: string | null;
  drop_lat: number;
  drop_lng: number;
  total_price: string;
  reassign_count: number;
  delay_flags: string[];
  items: OrderItem[];
}

export interface OrderEvent {
  id: string;
  type: string;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Rider {
  id: string;
  name: string;
  lat: number;
  lng: number;
  status: RiderStatus;
  active_order_ids: string[];
  capacity: number;
  vehicle: string;
  location_source: string;
  location_accuracy_m: number | null;
  last_seen_at: string | null;
}

export interface LiveRiderLocation {
  id: string;
  name: string;
  lat: number;
  lng: number;
  location_source: "gps" | "simulated";
  location_accuracy_m: number | null;
  last_seen_at: string | null;
}

export interface Customer {
  id: string;
  name: string;
  home_lat: number;
  home_lng: number;
  budget_pref: string | null;
  diet_pref: string | null;
}

export interface Restaurant {
  id: string;
  name: string;
  lat: number;
  lng: number;
  cuisine: string[];
  avg_prep_min: number;
  capacity_per_hr: number;
  rating: string;
  distance_km: number | null;
}

export interface MenuItem {
  id: string;
  name: string;
  price: string;
  category: string;
  veg: boolean;
  prep_complexity: number;
  tags: string[];
}

export interface Candidate {
  rider: Rider;
  score: number;
  pickup_distance_km: number;
  pickup_eta_min: number;
  active_load: number;
  reasons: string[];
}

export interface Assignment {
  order: Order;
  rider: Rider;
  score: number;
  reasons: string[];
}

export interface RiskOrder {
  order: Order;
  rider: Rider | null;
  severity: "warning" | "critical";
  flags: string[];
  minutes_remaining: number | null;
  minutes_since_last_event: number;
  risk_score: number;
  reasons: string[];
}

export interface MonitorSummary {
  active_orders: number;
  at_risk: number;
  late: number;
  stalled: number;
  avg_minutes_remaining: number | null;
}

export interface ScanResult {
  scanned: number;
  flagged: number;
  events_appended: number;
  orders: RiskOrder[];
}

export interface ModelMetrics {
  prep_mae: number;
  drive_mae: number;
  total_mae: number;
  p10_p90_coverage: number;
  avg_interval_width: number;
  n_train: number;
  n_val: number;
}

export interface ModelVersion {
  id: string;
  name: string;
  version: string;
  artifact_path: string | null;
  row_count: number;
  is_active: boolean;
  metrics: Record<string, number>;
  created_at: string;
}

export interface RetrainResult {
  version: string;
  promoted: boolean;
  improved: boolean;
  metrics: ModelMetrics;
  active_version: string | null;
  active_metrics: ModelMetrics | null;
}

export interface RestaurantRecommendation {
  restaurant: Restaurant;
  score: number;
  distance_km: number;
  reasons: string[];
}

export interface MenuRecommendation {
  item: MenuItem;
  score: number;
  reasons: string[];
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const TOKEN_KEY = "foodflow.token";
const USER_KEY = "foodflow.user";

export function getAuthToken(): string | null {
  return window.localStorage.getItem(TOKEN_KEY);
}

export function getStoredUser(): AuthUser | null {
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function storeSession(token: string, user: AuthUser): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  window.dispatchEvent(new Event("foodflow.session"));
}

export function clearSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
  window.dispatchEvent(new Event("foodflow.session"));
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAuthToken();
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });

  if (response.status === 204) {
    return undefined as T;
  }

  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail)) {
        detail = body.detail
          .map((item) => {
            if (item && typeof item === "object" && "msg" in item) {
              return String((item as { msg: unknown }).msg);
            }
            return JSON.stringify(item);
          })
          .join("; ");
      }
    } catch {
      // keep the status text when the body is not JSON
    }
    throw new ApiError(detail, response.status);
  }

  return (await response.json()) as T;
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : "";
}

export const getOrders = (status?: OrderStatus, limit = 60) =>
  request<Order[]>(`/orders${query({ status, limit })}`);

export const getOrderEvents = (orderId: string) =>
  request<OrderEvent[]>(`/orders/${orderId}/events`);

export const getRestaurants = () => request<Restaurant[]>("/restaurants");

export const getCustomers = () => request<Customer[]>("/customers");

export const getCandidates = (orderId: string) =>
  request<Candidate[]>(`/orders/${orderId}/candidates`);

export const assignOrder = (orderId: string, riderId?: string) =>
  request<Assignment>(`/orders/${orderId}/assign`, {
    method: "POST",
    body: JSON.stringify(riderId ? { rider_id: riderId } : {}),
  });

export const getMonitorSummary = () =>
  request<MonitorSummary>("/monitor/summary");

export const getAtRisk = (limit = 40) =>
  request<RiskOrder[]>(`/monitor/at-risk${query({ limit })}`);

export const scanMonitor = () =>
  request<ScanResult>("/monitor/scan", { method: "POST" });

export const getModels = () => request<ModelVersion[]>("/learning/models");

export const retrainModel = (force = false) =>
  request<RetrainResult>("/learning/retrain", {
    method: "POST",
    body: JSON.stringify({ force, min_rows: 500 }),
  });

export const getRestaurantRecommendations = (customerId: string, limit = 8) =>
  request<RestaurantRecommendation[]>(
    `/recommendations/restaurants/${customerId}${query({ limit })}`,
  );

export const getMenuRecommendations = (customerId: string, restaurantId: string) =>
  request<MenuRecommendation[]>(
    `/recommendations/menu/${customerId}/${restaurantId}`,
  );

export const orderSocketUrl = (orderId: string) =>
  `${WS_URL}/ws/orders/${orderId}?token=${encodeURIComponent(getAuthToken() ?? "")}`;

export type Role = "customer" | "rider" | "restaurant" | "admin";

export interface AuthUser {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  role: Role;
  is_active: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export interface BrowseRestaurant {
  id: string;
  name: string;
  cuisine: string[];
  rating: string;
  rating_count: number;
  avg_prep_min: number;
  min_order_value: string;
  delivery_fee: string;
  address: string | null;
  description: string;
  image_url: string | null;
  is_active: boolean;
  distance_km: number | null;
}

export interface BrowseMenuItem {
  id: string;
  name: string;
  price: string;
  category: string;
  veg: boolean;
  prep_complexity: number;
  tags: string[];
  available: boolean;
  description: string;
  image_url: string | null;
}

export interface CartLine {
  id: string;
  menu_item_id: string;
  name: string;
  price: string;
  qty: number;
  veg: boolean;
  available: boolean;
  line_total: string;
}

export interface Cart {
  id: string;
  restaurant: {
    id: string;
    name: string;
    image_url: string | null;
    delivery_fee: string;
    min_order_value: string;
    avg_prep_min: number;
  } | null;
  items: CartLine[];
  item_count: number;
  subtotal: string;
  delivery_fee: string;
  discount: string;
  tax: string;
  total: string;
  coupon_code: string | null;
}

export interface Coupon {
  code: string;
  valid: boolean;
  description: string;
  discount: string;
}

export interface MarketOrder {
  id: string;
  order_number: string | null;
  customer_id: string;
  restaurant_id: string;
  restaurant_name: string;
  rider_id: string | null;
  rider_name: string | null;
  status: OrderStatus;
  items: OrderItem[];
  subtotal: string;
  delivery_fee: string;
  discount: string;
  tax: string;
  total_amount: string;
  payment_method: string;
  payment_status: string;
  placed_at: string;
  promised_eta_at: string | null;
  deadline_at: string | null;
  actual_delivery_at: string | null;
  drop_lat: number;
  drop_lng: number;
  delivery_address: string | null;
  customer_phone: string | null;
  delivery_instructions: string | null;
  estimated_prep_min: number | null;
  delay_flags: string[];
  reassign_count: number;
  can_review: boolean;
}

export interface Address {
  id: string;
  label: string;
  line1: string;
  line2: string | null;
  city: string;
  lat: number;
  lng: number;
  phone: string | null;
  is_default: boolean;
}

export interface Profile {
  id: string;
  name: string;
  email: string | null;
  phone: string | null;
  home_lat: number;
  home_lng: number;
  budget_pref: string | null;
  diet_pref: string | null;
}

export interface RiderProfile {
  id: string;
  user_id: string;
  name: string;
  email: string | null;
  phone: string | null;
  lat: number;
  lng: number;
  location_source: string;
  location_accuracy_m: number | null;
  status: string;
  vehicle: string;
  vehicle_registration: string | null;
  capacity: number;
  verification_status: string;
  average_rating: number;
  active_order_ids: string[];
  last_seen_at: string | null;
  today_earnings: string;
  week_earnings: string;
  month_earnings: string;
  today_deliveries: number;
  total_deliveries: number;
}

export interface Offer {
  assignment_id: string;
  order_id: string;
  order_number: string | null;
  restaurant_name: string;
  restaurant_address: string | null;
  pickup_lat: number;
  pickup_lng: number;
  drop_lat: number;
  drop_lng: number;
  pickup_distance_km: number;
  pickup_eta_min: number;
  delivery_distance_km: number;
  estimated_delivery_min: number;
  estimated_earnings: string;
  expires_at: string;
  offered_at: string;
}

export interface AssignmentAction {
  assignment_id: string;
  status: string;
  order: MarketOrder;
}

export interface EarningsEntry {
  order_id: string;
  order_number: string | null;
  restaurant_name: string;
  amount: string;
  distance_km: number;
  created_at: string;
}

export interface Earnings {
  today: string;
  week: string;
  month: string;
  completed_deliveries: number;
  entries: EarningsEntry[];
}

export interface Tracking {
  order_id: string;
  order_number: string | null;
  status: OrderStatus;
  restaurant_name: string;
  restaurant_address: string | null;
  restaurant_lat: number;
  restaurant_lng: number;
  drop_lat: number;
  drop_lng: number;
  delivery_address: string | null;
  rider: {
    id: string;
    name: string;
    lat: number;
    lng: number;
    vehicle: string;
    phone: string | null;
    location_source: string;
    location_accuracy_m: number | null;
    last_seen_at: string | null;
  } | null;
  points: Array<{ lat: number; lng: number; created_at: string }>;
  eta_minutes: number | null;
  low_minutes: number | null;
  high_minutes: number | null;
  promised_eta_at: string | null;
  simulated: boolean;
}

export interface TrackingRoute {
  order_id: string;
  phase: "to_pickup" | "to_drop" | "restaurant_to_customer";
  origin: { lat: number; lng: number };
  destination: { lat: number; lng: number };
  points: Array<{ lat: number; lng: number }>;
  distance_m: number;
  duration_s: number;
  routing_provider: string;
  is_estimated: boolean;
}

export interface RestaurantAnalytics {
  active_orders: number;
  completed_today: number;
  revenue_today: string;
  average_prep_min: number | null;
  menu_items: number;
  available_items: number;
  rating: string;
  rating_count: number;
}

export interface InboxNotification {
  id: string;
  type: string;
  title: string;
  body: string;
  order_id: string | null;
  is_read: boolean;
  created_at: string;
}

export interface ReviewResult {
  id: string;
  order_id: string;
  restaurant_rating: number;
  rider_rating: number | null;
  comment: string | null;
  created_at: string;
}

export const login = (email: string, password: string) =>
  request<TokenResponse>("/api/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });

export const registerCustomer = (payload: {
  name: string;
  email: string;
  password: string;
  phone?: string;
}) =>
  request<TokenResponse>("/api/v1/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const getMe = () => request<AuthUser>("/api/v1/auth/me");

export const browseRestaurants = (params: {
  q?: string;
  cuisine?: string;
  veg?: boolean;
  min_rating?: number;
  lat?: number;
  lng?: number;
} = {}) =>
  request<BrowseRestaurant[]>(
    `/api/v1/restaurants${query({
      q: params.q,
      cuisine: params.cuisine,
      veg: params.veg === undefined ? undefined : String(params.veg),
      min_rating: params.min_rating,
      lat: params.lat,
      lng: params.lng,
    })}`,
  );

export const getMarketRestaurant = (restaurantId: string) =>
  request<BrowseRestaurant>(`/api/v1/restaurants/${restaurantId}`);

export const getMarketMenu = (restaurantId: string) =>
  request<BrowseMenuItem[]>(`/api/v1/restaurants/${restaurantId}/menu`);

export const getProfile = () => request<Profile>("/api/v1/me/profile");

export const updateProfile = (payload: Partial<Profile>) =>
  request<Profile>("/api/v1/me/profile", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const getAddresses = () => request<Address[]>("/api/v1/me/addresses");

export const addAddress = (payload: Omit<Address, "id">) =>
  request<Address>("/api/v1/me/addresses", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const deleteAddress = (addressId: string) =>
  request<void>(`/api/v1/me/addresses/${addressId}`, { method: "DELETE" });

export const getCart = () => request<Cart>("/api/v1/cart");

export const addCartItem = (menuItemId: string, qty = 1) =>
  request<Cart>("/api/v1/cart/items", {
    method: "POST",
    body: JSON.stringify({ menu_item_id: menuItemId, qty }),
  });

export const updateCartItem = (lineId: string, qty: number) =>
  request<Cart>(`/api/v1/cart/items/${lineId}`, {
    method: "PATCH",
    body: JSON.stringify({ qty }),
  });

export const removeCartItem = (lineId: string) =>
  request<Cart>(`/api/v1/cart/items/${lineId}`, { method: "DELETE" });

export const getCoupons = () => request<Coupon[]>("/api/v1/coupons");

export const applyCoupon = (code: string) =>
  request<Cart>("/api/v1/cart/coupon", {
    method: "POST",
    body: JSON.stringify({ code }),
  });

export const clearCoupon = () =>
  request<Cart>("/api/v1/cart/coupon", { method: "DELETE" });

export const checkout = (payload: {
  address_id?: string | null;
  phone?: string;
  instructions?: string;
  payment_method: "COD" | "UPI_DEMO";
  coupon_code?: string | null;
}) =>
  request<MarketOrder>("/api/v1/checkout", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const getMyOrders = () => request<MarketOrder[]>("/api/v1/orders");

export const getMyOrder = (orderId: string) =>
  request<MarketOrder>(`/api/v1/orders/${orderId}`);

export const cancelMyOrder = (orderId: string, reason?: string) =>
  request<MarketOrder>(`/api/v1/orders/${orderId}/cancel`, {
    method: "POST",
    body: JSON.stringify(reason ? { reason } : {}),
  });

export const reorder = (orderId: string) =>
  request<Cart>(`/api/v1/orders/${orderId}/reorder`, { method: "POST" });

export const reviewOrder = (
  orderId: string,
  payload: { restaurant_rating: number; rider_rating?: number; comment?: string },
) =>
  request<ReviewResult>(`/api/v1/orders/${orderId}/review`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const getTracking = (orderId: string) =>
  request<Tracking>(`/api/v1/orders/${orderId}/tracking`);

export const getTrackingRoute = (orderId: string) =>
  request<TrackingRoute>(`/api/v1/orders/${orderId}/route`);

export const getRiderProfile = () =>
  request<RiderProfile>("/api/v1/rider/me");

export const setRiderAvailability = (online: boolean) =>
  request<RiderProfile>("/api/v1/rider/availability", {
    method: "POST",
    body: JSON.stringify({ online }),
  });

export const pingRiderLocation = (
  lat: number,
  lng: number,
  options?: { source?: "gps" | "simulated"; accuracy_m?: number | null },
) =>
  request<RiderProfile>("/api/v1/rider/location", {
    method: "POST",
    body: JSON.stringify({
      lat,
      lng,
      source: options?.source ?? "simulated",
      accuracy_m: options?.accuracy_m ?? null,
    }),
  });

export const getOffers = () => request<Offer[]>("/api/v1/rider/offers");

export const acceptOffer = (assignmentId: string) =>
  request<AssignmentAction>(`/api/v1/rider/offers/${assignmentId}/accept`, {
    method: "POST",
    body: "{}",
  });

export const rejectOffer = (assignmentId: string, reason?: string) =>
  request<{ status: string; next_offer: Offer | null }>(
    `/api/v1/rider/offers/${assignmentId}/reject`,
    { method: "POST", body: JSON.stringify(reason ? { reason } : {}) },
  );

export const getActiveDelivery = () =>
  request<AssignmentAction | null>("/api/v1/rider/deliveries/active");

export const getDeliveryHistory = () =>
  request<MarketOrder[]>("/api/v1/rider/deliveries/history");

export const getEarnings = () => request<Earnings>("/api/v1/rider/earnings");

export const riderAssignmentAction = (
  assignmentId: string,
  action: "arrived-restaurant" | "pickup" | "arrived-customer" | "complete",
) =>
  request<AssignmentAction>(
    `/api/v1/rider/assignments/${assignmentId}/${action}`,
    { method: "POST", body: "{}" },
  );

export const getManagerRestaurant = () =>
  request<BrowseRestaurant>("/api/v1/restaurant/me");

export const getManagerMenu = () =>
  request<BrowseMenuItem[]>("/api/v1/restaurant/menu");

export const patchManagerMenuItem = (
  itemId: string,
  payload: { available?: boolean; price?: string; description?: string },
) =>
  request<BrowseMenuItem>(`/api/v1/restaurant/menu/${itemId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export const getRestaurantOrders = (status?: OrderStatus) =>
  request<MarketOrder[]>(
    `/api/v1/restaurant/orders${query({ status, limit: 100 })}`,
  );

export const restaurantOrderAction = (
  orderId: string,
  action: "accept" | "reject" | "prepare" | "ready",
  reason?: string,
) =>
  request<MarketOrder>(
    `/api/v1/restaurant/orders/${orderId}/${action}`,
    { method: "POST", body: JSON.stringify(reason ? { reason } : {}) },
  );

export const getRestaurantAnalytics = () =>
  request<RestaurantAnalytics>("/api/v1/restaurant/analytics");

export const getNotifications = (limit = 30) =>
  request<InboxNotification[]>(`/api/v1/notifications${query({ limit })}`);

export const markNotificationRead = (id: string) =>
  request<InboxNotification>(`/api/v1/notifications/${id}/read`, {
    method: "POST",
    body: "{}",
  });

export const markAllNotificationsRead = () =>
  request<{ updated: number }>("/api/v1/notifications/read-all", {
    method: "POST",
    body: "{}",
  });

export const authOrderSocketUrl = (orderId: string) =>
  `${WS_URL}/ws/v1/orders/${orderId}?token=${encodeURIComponent(getAuthToken() ?? "")}`;

export const restaurantOrderSocketUrl = () =>
  `${WS_URL}/ws/v1/restaurant/orders?token=${encodeURIComponent(getAuthToken() ?? "")}`;

export const notificationSocketUrl = () =>
  `${WS_URL}/ws/notifications?token=${encodeURIComponent(getAuthToken() ?? "")}`;
