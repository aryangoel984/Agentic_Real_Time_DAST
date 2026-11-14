"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useSession } from "../lib/session";

const NAV = [
  { href: "/bookings", label: "Bookings" },
  { href: "/search", label: "Search" },
  { href: "/users", label: "Users" },
  { href: "/console", label: "Request console" },
];

export default function Header() {
  const { user, logout } = useSession();
  const pathname = usePathname();
  const router = useRouter();

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-3 px-6 py-4">
        <Link href="/" className="text-lg font-semibold tracking-tight">
          TravelHub <span className="font-normal text-slate-400">B2B</span>
        </Link>
        {user && (
          <nav className="flex flex-wrap gap-1">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className={`rounded-md px-3 py-1.5 text-sm ${
                  pathname.startsWith(n.href)
                    ? "bg-slate-100 font-medium text-slate-900"
                    : "text-slate-600 hover:text-slate-900"
                }`}
              >
                {n.label}
              </Link>
            ))}
          </nav>
        )}
        <div className="ml-auto flex items-center gap-4">
          {user ? (
            <>
              <div className="text-right text-sm leading-tight">
                <div className="font-medium">
                  {user.full_name} <span className="font-mono text-xs text-slate-400">({user.username})</span>
                </div>
                <div className="text-slate-500">
                  {user.agency_name} · <span className="capitalize">{user.role}</span>
                </div>
              </div>
              <button
                className="btn-ghost"
                onClick={() => {
                  logout();
                  router.push("/login");
                }}
              >
                Log out
              </button>
            </>
          ) : (
            <span className="text-sm text-slate-500">Not logged in</span>
          )}
        </div>
      </div>
    </header>
  );
}
