"use client";

/**
 * Translation keys from commit one.
 *
 * Only English is populated today, but every user-facing string goes through `t()` so adding
 * Tamil is a data change rather than a refactor of every component. §5.2: a factory owner in
 * Tiruppur should be able to read their own profile form.
 */
export type Language = "en" | "ta";

type Dictionary = Record<string, string>;

const en: Dictionary = {
  "app.name": "Buying House",
  "nav.dashboard": "Dashboard",
  "nav.suppliers": "Suppliers",
  "nav.brands": "Brands",
  "nav.masterData": "Master data",
  "nav.dataEditor": "Data editor",
  "nav.myProfile": "My profile",
  "nav.signOut": "Sign out",

  "auth.signIn": "Sign in",
  "auth.email": "Email",
  "auth.password": "Password",
  "auth.phone": "Phone number",
  "auth.otpCode": "6-digit code",
  "auth.sendCode": "Send code",
  "auth.useOtp": "Sign in with a code instead",
  "auth.usePassword": "Sign in with email and password",
  "auth.otpSent": "If that number is registered, a code has been sent.",

  "supplier.register": "Register a supplier",
  "supplier.factoryName": "Factory name",
  "supplier.city": "City",
  "supplier.country": "Country",
  "supplier.primaryProcess": "Main process",
  "supplier.primaryCategory": "Main product",
  "supplier.contactName": "Contact person",
  "supplier.phone": "Phone",
  "supplier.whatsapp": "WhatsApp",
  "supplier.completeness": "Profile completeness",
  "supplier.tier": "Tier",
  "supplier.processes": "Processes",
  "supplier.capabilities": "Capabilities",
  "supplier.certifications": "Certifications",
  "supplier.capacity": "Monthly capacity",
  "supplier.moq": "Minimum order",
  "supplier.leadTime": "Lead time",
  "supplier.submitForReview": "Submit for review",

  "directory.title": "Supplier directory",
  "directory.search": "Search by name or city",
  "directory.noResults": "No suppliers match these filters.",
  "directory.identityHidden": "Identity withheld until revealed",

  "verification.verify": "Verify",
  "verification.needsInfo": "Request more information",
  "verification.reject": "Reject",

  "common.save": "Save",
  "common.cancel": "Cancel",
  "common.loading": "Loading…",
  "common.none": "—",
};

// Populated as translations arrive; missing keys fall back to English rather than showing raw
// key names to a user.
const ta: Dictionary = {
  "app.name": "பையிங் ஹவுஸ்",
  "nav.myProfile": "என் விவரக்குறிப்பு",
  "nav.signOut": "வெளியேறு",
  "auth.phone": "தொலைபேசி எண்",
  "auth.otpCode": "6 இலக்க குறியீடு",
  "auth.sendCode": "குறியீட்டை அனுப்பு",
  "supplier.factoryName": "தொழிற்சாலை பெயர்",
  "supplier.city": "நகரம்",
  "supplier.contactName": "தொடர்பு நபர்",
  "supplier.phone": "தொலைபேசி",
  "supplier.whatsapp": "வாட்ஸ்அப்",
  "supplier.completeness": "விவரக்குறிப்பு நிறைவு",
  "common.save": "சேமி",
  "common.cancel": "ரத்து",
};

const dictionaries: Record<Language, Dictionary> = { en, ta };

export function translate(key: string, language: Language = "en"): string {
  return dictionaries[language]?.[key] ?? en[key] ?? key;
}
