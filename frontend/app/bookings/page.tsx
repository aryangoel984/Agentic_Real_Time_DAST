"use client";

import { useState } from "react";
import RequireLogin from "../components/RequireLogin";
import ResponseBox from "../components/ResponseBox";
import { apiRequest, ApiResult, inr } from "../lib/api";
import { CurrentUser, useSession } from "../lib/session";

type Booking = {
  id: number;
  agency_id: number;
  agency_name: string;
  booked_by_user_id: number;
  customer_name: string;
  customer_email: string;
  customer_phone: string;
  item: string;
  travel_date: string;
  amount: number;
  payment_status: string;
  total_paid: number;
  refund_eligible: boolean;
  refund_status: string;
  total_refunded: number;
};

export default function BookingsPage() {
  return (
    <RequireLogin>
      <Bookings />
    </RequireLogin>
  );
}

function Bookings() {
  const { user } = useSession();
  const [lookupId, setLookupId] = useState("1001");
  const [booking, setBooking] = useState<Booking | null>(null);
  const [lookupResult, setLookupResult] = useState<ApiResult | null>(null);
  const [payTarget, setPayTarget] = useState({ id: "", amount: "" });
  const [refundTarget, setRefundTarget] = useState({ id: "", amount: "" });

  async function lookup(id: string) {
    const res = await apiRequest("GET", `/api/bookings/${encodeURIComponent(id)}`);
    setLookupResult(res);
    if (res.ok) {
      const b = res.data as Booking;
      setBooking(b);
      setPayTarget({ id: String(b.id), amount: String(b.amount) });
      setRefundTarget({ id: String(b.id), amount: String(b.total_paid || b.amount) });
    } else {
      setBooking(null);
    }
  }

  // After paying/refunding, reload the booking shown on screen so totals update.
  function refreshIfShown(id: string) {
    if (booking && String(booking.id) === id) lookup(id);
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Bookings</h1>
        <p className="mt-1 text-sm text-slate-500">Look up, pay for, refund, and create bookings. Seeded booking IDs: 1001–1008.</p>
      </div>

      <section className="card">
        <h2 className="font-semibold">Look up a booking</h2>
        <form onSubmit={(e) => { e.preventDefault(); lookup(lookupId); }} className="mt-4 flex gap-3">
          <input className="input max-w-48 font-mono" value={lookupId} onChange={(e) => setLookupId(e.target.value)} placeholder="Booking ID" />
          <button className="btn">Look up</button>
        </form>
        {booking && user && <BookingCard b={booking} user={user} />}
        <ResponseBox result={lookupResult} />
      </section>

      <div className="grid gap-8 lg:grid-cols-2">
        <PayPanel target={payTarget} setTarget={setPayTarget} onDone={refreshIfShown} />
        <RefundPanel user={user!} target={refundTarget} setTarget={setRefundTarget} onDone={refreshIfShown} />
      </div>

      <CreatePanel user={user!} onCreated={(id) => { setLookupId(String(id)); lookup(String(id)); }} />
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="label">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

function Pill({ tone, children }: { tone: "green" | "amber" | "slate" | "red"; children: React.ReactNode }) {
  const tones = {
    green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
    amber: "bg-amber-50 text-amber-800 ring-amber-200",
    red: "bg-red-50 text-red-700 ring-red-200",
    slate: "bg-slate-100 text-slate-600 ring-slate-200",
  };
  return <span className={`rounded-md px-2 py-0.5 text-xs font-medium ring-1 ${tones[tone]}`}>{children}</span>;
}

function BookingCard({ b, user }: { b: Booking; user: CurrentUser }) {
  const foreign = b.agency_id !== user.agency_id;
  const overRefunded = b.total_refunded > b.total_paid;
  const underPaid = b.payment_status === "paid" && b.total_paid < b.amount;
  return (
    <div className="mt-6 overflow-hidden rounded-xl border border-slate-200">
      {foreign && (
        <div className="border-b border-red-200 bg-red-50 px-5 py-3 text-sm text-red-800">
          <strong>Another agency&apos;s booking.</strong> This belongs to {b.agency_name}, but you are logged in as{" "}
          {user.agency_name}.
        </div>
      )}
      <div className="flex flex-wrap items-baseline gap-3 px-5 pt-5">
        <span className="font-mono text-sm text-slate-400">#{b.id}</span>
        <span className="text-lg font-semibold">{b.item}</span>
        <span className="ml-auto text-xl font-semibold">{inr(b.amount)}</span>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 gap-y-5 px-5 py-5 md:grid-cols-4">
        <Field label="Agency">{b.agency_name}</Field>
        <Field label="Customer">{b.customer_name}</Field>
        <Field label="Email">{b.customer_email}</Field>
        <Field label="Phone">{b.customer_phone}</Field>
        <Field label="Travel date">{b.travel_date}</Field>
        <Field label="Payment">
          <Pill tone={b.payment_status === "paid" ? "green" : "slate"}>{b.payment_status}</Pill>
        </Field>
        <Field label="Paid">
          <span className={underPaid ? "font-semibold text-red-700" : ""}>{inr(b.total_paid)}</span>
        </Field>
        <Field label="Refund">
          {b.refund_eligible ? (
            <Pill tone={b.refund_status === "refunded" ? "amber" : "slate"}>
              {b.refund_status === "refunded" ? "refunded" : "eligible"}
            </Pill>
          ) : (
            <Pill tone="slate">non-refundable</Pill>
          )}
        </Field>
        <Field label="Refunded">
          <span className={overRefunded ? "font-semibold text-red-700" : ""}>{inr(b.total_refunded)}</span>
        </Field>
      </dl>
      {(underPaid || overRefunded) && (
        <div className="border-t border-red-200 bg-red-50 px-5 py-3 text-sm text-red-800">
          {underPaid && <div>Marked paid, but only {inr(b.total_paid)} was paid against a price of {inr(b.amount)}.</div>}
          {overRefunded && <div>Refunded {inr(b.total_refunded)}, which is more than the {inr(b.total_paid)} that was paid.</div>}
        </div>
      )}
    </div>
  );
}

type Target = { id: string; amount: string };

function PayPanel({ target, setTarget, onDone }: { target: Target; setTarget: (t: Target) => void; onDone: (id: string) => void }) {
  const [result, setResult] = useState<ApiResult | null>(null);
  async function pay(e: React.FormEvent) {
    e.preventDefault();
    const res = await apiRequest("POST", "/api/payments", { booking_id: Number(target.id), amount: Number(target.amount) });
    setResult(res);
    onDone(target.id);
  }
  return (
    <section className="card">
      <h2 className="font-semibold">Pay for a booking</h2>
      <p className="mt-1 text-sm text-slate-500">Amount is pre-filled with the booking price after a lookup.</p>
      <form onSubmit={pay} className="mt-4 grid grid-cols-2 gap-4">
        <div>
          <label className="label">Booking ID</label>
          <input className="input font-mono" value={target.id} onChange={(e) => setTarget({ ...target, id: e.target.value })} required />
        </div>
        <div>
          <label className="label">Amount (₹)</label>
          <input className="input font-mono" type="number" min="0" step="any" value={target.amount}
            onChange={(e) => setTarget({ ...target, amount: e.target.value })} required />
        </div>
        <button className="btn col-span-2">Pay</button>
      </form>
      <ResponseBox result={result} />
    </section>
  );
}

function RefundPanel({ user, target, setTarget, onDone }: { user: CurrentUser; target: Target; setTarget: (t: Target) => void; onDone: (id: string) => void }) {
  const [result, setResult] = useState<ApiResult | null>(null);
  async function refund(e: React.FormEvent) {
    e.preventDefault();
    const res = await apiRequest("POST", "/api/refunds", { booking_id: Number(target.id), amount: Number(target.amount) });
    setResult(res);
    onDone(target.id);
  }
  return (
    <section className="card">
      <h2 className="font-semibold">Refund a booking</h2>
      {user.role !== "admin" ? (
        <p className="mt-3 text-sm text-slate-500">Only agency admins can issue refunds. Log in as an admin account to use this.</p>
      ) : (
        <>
          <p className="mt-1 text-sm text-slate-500">Refunds a paid, refundable booking.</p>
          <form onSubmit={refund} className="mt-4 grid grid-cols-2 gap-4">
            <div>
              <label className="label">Booking ID</label>
              <input className="input font-mono" value={target.id} onChange={(e) => setTarget({ ...target, id: e.target.value })} required />
            </div>
            <div>
              <label className="label">Amount (₹)</label>
              <input className="input font-mono" type="number" min="0" step="any" value={target.amount}
                onChange={(e) => setTarget({ ...target, amount: e.target.value })} required />
            </div>
            <button className="btn col-span-2">Refund</button>
          </form>
          <ResponseBox result={result} />
        </>
      )}
    </section>
  );
}

function CreatePanel({ user, onCreated }: { user: CurrentUser; onCreated: (id: number) => void }) {
  const [form, setForm] = useState({
    user_id: String(user.id), agency_id: String(user.agency_id), amount: "12000",
    customer_name: "Test Customer", customer_email: "test.customer@example.com",
    customer_phone: "+91-90000-09999", item: "Flight DEL-BOM FL-221, 1 pax", travel_date: "2026-12-24",
  });
  const [result, setResult] = useState<ApiResult | null>(null);
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value });

  async function create(e: React.FormEvent) {
    e.preventDefault();
    const res = await apiRequest("POST", "/api/bookings", {
      ...form, user_id: Number(form.user_id), agency_id: Number(form.agency_id), amount: Number(form.amount),
    });
    setResult(res);
    if (res.ok) onCreated((res.data as { id: number }).id);
  }

  const fields: [keyof typeof form, string][] = [
    ["customer_name", "Customer name"], ["customer_email", "Customer email"], ["customer_phone", "Customer phone"],
    ["item", "Item"], ["travel_date", "Travel date"], ["amount", "Amount (₹)"],
    ["user_id", "Booked by user ID"], ["agency_id", "Agency ID"],
  ];
  return (
    <section className="card">
      <h2 className="font-semibold">Create a booking</h2>
      <form onSubmit={create} className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {fields.map(([k, label]) => (
          <div key={k}>
            <label className="label">{label}</label>
            <input className="input" value={form[k]} onChange={set(k)} required />
          </div>
        ))}
        <button className="btn sm:col-span-2 lg:col-span-4">Create booking</button>
      </form>
      <ResponseBox result={result} />
    </section>
  );
}
