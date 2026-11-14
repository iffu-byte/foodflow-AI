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
  image_credit?: PhotoCredit | null;
  kitchen_type?: string;
  price_parity?: boolean;
  trust_score?: number | null;
  trust_grade?: string | null;
  trust_badges?: string[];
  trust_warnings?: string[];
  rescue_live?: number;
  matching_dishes?: Array<{
    id: string;
    name: string;
    price: string;
    veg: boolean;
    portion_grams: number | null;
  }>;
}

export interface PhotoCredit {
  source: string;
  author?: string;
  licence?: string;
  licence_url?: string | null;
  page_url?: string | null;
  title?: string;
  dish?: string;
}

export interface NutritionView {
  grams: number;
  grams_source: "measured" | "declared" | "typical";
  kcal: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fibre_g: number;
  allergens: string[];
  source: string | null;
  confidence: number | null;
  estimate: boolean;
}

export interface RescueDeal {
  id: string;
  restaurant_id: string;
  restaurant_name: string | null;
  menu_item_id: string;
  name: string;
  veg: boolean;
  portion_grams: number | null;
  original_price: string;
  current_price: string;
  price_in_10_min: string;
  floor_price: string;
  discount_pct: number;
  qty_left: number;
  qty_total: number;
  starts_at: string;
  ends_at: string;
  status: string;
  distance_km: number | null;
}

export interface DeliveryProof {
  method: string;
  verified_at: string;
  distance_m: number;
  radius_m: number;
  location_source: string;
  location_accuracy_m: number | null;
}

export interface BatchDrop {
  assignment_id: string;
  order_id: string;
  order_number: string | null;
  sequence: number;
  status: string;
  delivery_address: string | null;
  drop_lat: number;
  drop_lng: number;
  shared: boolean;
}

export interface DelaySegment {
  owner: "restaurant" | "platform" | "rider";
  stage: string;
  expected_min: number;
  actual_min: number;
  over_min: number;
}

export interface HonestStatus {
  order_id: string;
  status: OrderStatus;
  headline: string;
  detail: string;
  waiting_on: "restaurant" | "platform" | "rider" | "none";
  minutes_since_placed: number;
  riders_asked: number;
  live_eta_min: number | null;
  promised_min_left: number | null;
  running_late: boolean;
  free_cancel: string | null;
  can_cancel: boolean;
  batch: {
    size: number;
    your_drop: number | null;
    drops: Array<{ sequence: number | null; is_you: boolean; status: string }>;
    saving: string;
  } | null;
  delivery_mode: "solo" | "shared";
  attribution: {
    segments: DelaySegment[];
    over_by_owner: Record<string, number>;
    late_min: number | null;
    message?: string | null;
  } | null;
  compensation: string;
  proof: DeliveryProof | null;
  estimate_basis: string;
}

export interface TrustComponent {
  key: string;
  label: string;
  points: number;
  max: number;
  detail: string;
}

export interface PlaceReview {
  rating: number | null;
  text: string;
  author: string | null;
  relative_time: string | null;
  flags?: string[];
}

export interface TrustProfile {
  restaurant_id: string;
  restaurant_name: string;
  lat: number;
  lng: number;
  address: string | null;
  kitchen_type: string;
  price_parity: boolean;
  fssai: {
    status: "missing" | "invalid" | "expired" | "format_ok";
    label: string;
    number: string | null;
    kind: string | null;
    valid_until: string | null;
    verify_url: string;
  };
  reality: {
    provider: "google" | "osm" | "none";
    verdict: string;
    checked_at: string;
    match?: {
      place_id: string | null;
      name: string;
      address: string | null;
      distance_m: number | null;
      name_similarity: number;
      rating: number | null;
      rating_count: number | null;
      business_status: string | null;
      maps_url: string | null;
      opening_hours: string[];
      photos: Array<{ url: string; attribution: string }>;
      reviews: PlaceReview[];
    } | null;
    signals?: {
      quantity_mentions: number;
      cloud_kitchen_mentions: number;
      hygiene_mentions: number;
      reviews_read: number;
    };
    osm?: {
      food_places_at_pin: Array<{
        name: string;
        amenity: string | null;
        distance_m: number | null;
        name_similarity: number;
      }>;
      object_at_pin: {
        category: string | null;
        type: string | null;
        name: string | null;
        distance_m?: number | null;
      } | null;
      address: string | null;
    } | null;
  };
  shared_kitchen: Array<{ id: string; name: string; kitchen_type: string }>;
  kitchen_photos: Array<{ id: string; url: string; caption: string; taken_at: string }>;
  quantity_feedback: { as_described: number; short: number };
  portion_coverage: { menu_items: number; declared: number; verified: number };
  providers: { google_maps: boolean; openstreetmap: boolean };
  score: number;
  grade: string;
  components: TrustComponent[];
  badges: string[];
  warnings: string[];
}

export interface NutritionToday {
  goal_kcal: number;
  goal_is_default: boolean;
  totals: { kcal: number; protein_g: number; carbs_g: number; fat_g: number; fibre_g: number };
  remaining_kcal: number;
  lines: Array<{
    order_id: string;
    order_number: string | null;
    name: string;
    qty: number;
    kcal: number;
    protein_g: number;
  }>;
  estimate: boolean;
}

export interface PortionEstimate {
  menu_item_id: string;
  method: string;
  grams: number;
  low_grams: number;
  high_grams: number;
  serves: number;
  confidence: number;
  explanation: string[];
  ai_check: {
    provider: string;
    dish_detected: string | null;
    matches_menu_item: boolean | null;
    estimated_grams: number | null;
    pieces: number | null;
    reference_visible: boolean | null;
    looks_real_photo: boolean | null;
    notes: string | null;
    agreement: string | null;
    cost_usd: number;
  } | null;
  ai_available: boolean;
}

export interface PortionConfig {
  references: Array<{ key: string; cm: number | null; label: string }>;
  profiles: Array<{ key: string; label: string; depth_cm: number; fill: number; density: number }>;
  ai_available: boolean;
}

export interface ForecastRow {
  menu_item_id: string;
  name: string;
  price: string;
  prepared: number | null;
  sold_today: number;
  pace_per_hour: number;
  projected_leftover: number | null;
  suggestion: {
    qty: number;
    start_price: string;
    floor_price: string;
    duration_min: number;
    reason: string;
  } | null;
  live_listing: RescueDeal | null;
}

export interface RescueForecast {
  day: string;
  closing_at: string;
  hours_to_close: number;
  horizon_hours: number;
  method: string;
  items: ForecastRow[];
}

export interface AiUsage {
  since: string;
  budget_usd: number;
  spent_usd: number;
  remaining_usd: number;
  calls: number;
  cache_hits: number;
  cache_hit_rate: number | null;
  gemini_enabled: boolean;
  google_maps_enabled: boolean;
  lines: Array<{
    provider: string;
    purpose: string;
    calls: number;
    cache_hits: number;
    input_tokens: number;
    output_tokens: number;
    est_cost_usd: number;
  }>;
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
  image_credit?: PhotoCredit | null;
  portion_grams?: number | null;
  portion_serves?: number | null;
  portion_pieces?: number | null;
  portion_method?: string;
  portion_confidence?: number | null;
  portion_photo_url?: string | null;
  portion_verified_at?: string | null;
  nutrition?: NutritionView | null;
  rescue?: RescueDeal | null;
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
  original_price?: string | null;
  rescue_listing_id?: string | null;
  rescue_ends_at?: string | null;
  kcal?: number | null;
  protein_g?: number | null;
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
  nutrition?: {
    kcal: number;
    protein_g: number;
    carbs_g: number;
    fat_g: number;
    allergens: string[];
    estimate: boolean;
  } | null;
  rescue_saving?: string;
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
  delivery_otp?: string | null;
  delivery_mode?: "solo" | "shared";
  shared_saving?: string;
  batch_id?: string | null;
  batch_sequence?: number | null;
  compensation?: string;
  delivery_proof?: DeliveryProof | null;
  otp_attempts?: number;
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
  daily_kcal_goal?: number | null;
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
  batched_with?: string | null;
  batch_extra_km?: number | null;
}

export interface AssignmentAction {
  assignment_id: string;
  status: string;
  order: MarketOrder;
  batch?: BatchDrop[] | null;
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
  sort?: "trust" | "rating";
} = {}) =>
  request<BrowseRestaurant[]>(
    `/api/v1/restaurants${query({
      q: params.q,
      cuisine: params.cuisine,
      veg: params.veg === undefined ? undefined : String(params.veg),
      min_rating: params.min_rating,
      lat: params.lat,
      lng: params.lng,
      sort: params.sort,
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

export const addCartItem = (menuItemId: string, qty = 1, rescueListingId?: string) =>
  request<Cart>("/api/v1/cart/items", {
    method: "POST",
    body: JSON.stringify({
      menu_item_id: menuItemId,
      qty,
      ...(rescueListingId ? { rescue_listing_id: rescueListingId } : {}),
    }),
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
  delivery_mode?: "solo" | "shared";
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
  payload: {
    restaurant_rating: number;
    rider_rating?: number;
    comment?: string;
    quantity_feedback?: "as_described" | "more" | "less" | "much_less";
  },
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
  otp?: string,
) =>
  request<AssignmentAction>(
    `/api/v1/rider/assignments/${assignmentId}/${action}`,
    { method: "POST", body: JSON.stringify(otp ? { otp } : {}) },
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

// --- Trust layer -----------------------------------------------------------

export const mediaUrl = (path: string | null | undefined): string | null =>
  path ? (path.startsWith("http") ? path : `${API_URL}${path}`) : null;

export const getRestaurantTrust = (restaurantId: string, refresh = false) =>
  request<TrustProfile>(
    `/api/v1/restaurants/${restaurantId}/trust${refresh ? "?refresh=true" : ""}`,
  );

export const getRescueLive = (lat?: number, lng?: number) =>
  request<RescueDeal[]>(`/api/v1/rescue/live${query({ lat, lng })}`);

export const getNutritionToday = () =>
  request<NutritionToday>("/api/v1/me/nutrition/today");

export const getHonestStatus = (orderId: string) =>
  request<HonestStatus>(`/api/v1/orders/${orderId}/honest-status`);

export const reportNotReceived = (orderId: string, note?: string) =>
  request<{ verdict: string; message: string; proof: DeliveryProof | null }>(
    `/api/v1/orders/${orderId}/not-received`,
    { method: "POST", body: JSON.stringify(note ? { note } : {}) },
  );

export const getMyTrust = (refresh = false) =>
  request<TrustProfile>(`/api/v1/restaurant/trust${refresh ? "?refresh=true" : ""}`);

export const patchMyTrust = (payload: {
  fssai_license?: string;
  fssai_valid_until?: string;
  kitchen_type?: "dine_in" | "cloud_kitchen" | "shared_kitchen";
  price_parity?: boolean;
}) =>
  request<TrustProfile>("/api/v1/restaurant/trust", {
    method: "PATCH",
    body: JSON.stringify(payload),
  });

export interface ListingCandidate {
  place_id: string | null;
  name: string;
  address: string | null;
  distance_m: number | null;
  rating: number | null;
  rating_count: number | null;
}

export const searchMyListing = (q?: string) =>
  request<{ provider: string; candidates: ListingCandidate[] }>(
    `/api/v1/restaurant/places/search${query({ q })}`,
  );

export const linkMyListing = (placeId: string) =>
  request<TrustProfile>("/api/v1/restaurant/places/link", {
    method: "POST",
    body: JSON.stringify({ place_id: placeId }),
  });

export const uploadKitchenPhoto = (image: string, caption: string) =>
  request<{ id: string; url: string; caption: string; taken_at: string }>(
    "/api/v1/restaurant/kitchen-photos",
    { method: "POST", body: JSON.stringify({ image, caption }) },
  );

export const getPortionConfig = () =>
  request<PortionConfig>("/api/v1/restaurant/portion/config");

export const estimatePortion = (itemId: string, payload: Record<string, unknown>) =>
  request<PortionEstimate>(`/api/v1/restaurant/menu/${itemId}/portion/estimate`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const publishPortion = (
  itemId: string,
  payload: {
    method: string;
    grams?: number | null;
    serves?: number | null;
    pieces?: number | null;
    confidence?: number | null;
    image?: string | null;
  },
) =>
  request<BrowseMenuItem>(`/api/v1/restaurant/menu/${itemId}/portion`, {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const getRescueForecast = () =>
  request<RescueForecast>("/api/v1/restaurant/rescue/forecast");

export const logPrep = (menuItemId: string, preparedQty: number) =>
  request<RescueForecast>("/api/v1/restaurant/rescue/prep", {
    method: "POST",
    body: JSON.stringify({ menu_item_id: menuItemId, prepared_qty: preparedQty }),
  });

export const createRescue = (payload: {
  menu_item_id: string;
  qty: number;
  start_price: string;
  floor_price: string;
  duration_min: number;
}) =>
  request<RescueDeal>("/api/v1/restaurant/rescue/listings", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const endRescue = (listingId: string) =>
  request<RescueForecast>(`/api/v1/restaurant/rescue/listings/${listingId}/end`, {
    method: "POST",
    body: "{}",
  });

export const getAiUsage = () => request<AiUsage>("/api/v1/ai/usage");

/** Downscale a photo in the browser before upload (keeps payloads small). */
export async function fileToDataUrl(file: File, maxSide = 1280, quality = 0.85): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Canvas is not available in this browser.");
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return canvas.toDataURL("image/jpeg", quality);
}

export const uploadDishPhoto = (itemId: string, image: string) =>
  request<BrowseMenuItem>(`/api/v1/restaurant/menu/${itemId}/photo`, {
    method: "POST",
    body: JSON.stringify({ image }),
  });
