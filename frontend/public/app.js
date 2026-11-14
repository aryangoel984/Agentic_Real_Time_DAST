/*
 * TravelHub B2B portal — frontend API client (mock "production bundle").
 *
 * This is what a browser would download. A scanner can read it to learn
 * which API routes the current app actually calls.
 *
 * Deliberately NOT listed here:
 *   - /api/v1/bookings/{id}           (old version, retired from the UI)
 *   - /api/internal/partner-details   (internal job only, never in the UI)
 */
const API_BASE = ""; // same origin: the portal forwards /api/* to the backend

const ROUTES = {
  login:         { method: "POST", path: "/api/login" },
  search:        { method: "GET",  path: "/api/search" },
  createBooking: { method: "POST", path: "/api/bookings" },
  getBooking:    { method: "GET",  path: "/api/bookings/:id" },
  pay:           { method: "POST", path: "/api/payments" },
  refund:        { method: "POST", path: "/api/refunds" },
  getUser:       { method: "GET",  path: "/api/users/:id" },
};

let authToken = null;

async function call(route, { params = {}, query = null, body = null } = {}) {
  let path = route.path.replace(/:(\w+)/g, (_, k) => encodeURIComponent(params[k]));
  if (query) path += "?" + new URLSearchParams(query).toString();
  const res = await fetch(API_BASE + path, {
    method: route.method,
    headers: {
      "Content-Type": "application/json",
      ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${route.method} ${path} -> ${res.status}`);
  return res.json();
}

export const api = {
  async login(username, password) {
    const data = await call(ROUTES.login, { body: { username, password } });
    authToken = data.token;
    return data;
  },
  search: (type, origin, destination) =>
    call(ROUTES.search, { query: { type, origin, destination } }),
  createBooking: (booking) => call(ROUTES.createBooking, { body: booking }),
  getBooking: (id) => call(ROUTES.getBooking, { params: { id } }),
  pay: (bookingId, amount) =>
    call(ROUTES.pay, { body: { booking_id: bookingId, amount } }),
  refund: (bookingId, amount) =>
    call(ROUTES.refund, { body: { booking_id: bookingId, amount } }),
  getUser: (id) => call(ROUTES.getUser, { params: { id } }),
};
