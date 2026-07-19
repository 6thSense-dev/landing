/**
 * Legal-page content manifest — single source of truth for /privacy and /terms.
 *
 * Mirrors the shape of productPages in ./pages.js so it can reuse the SAME
 * build-time prerender (scripts/seoPrerenderPlugin.js → crawlable static
 * dist/<path>/index.html) and the same light-paper layout (src/pages/product.css).
 *
 * These pages are load-bearing: Apple App Store and Google Play both require a
 * public privacy-policy URL for the synapse / Perle capture app. Keep the copy
 * HONEST and specific to what we actually do — record video, tactile-glove, and
 * IMU/motion data, upload it to AWS S3, and use it to build robotics training
 * datasets. Do not add boilerplate that misstates the product.
 *
 * A section `body` may be a string OR an array of strings (rendered as multiple
 * paragraphs). `items` renders a bullet list. `contact: true` renders the
 * ops@6thsense.dev mailto affordance.
 *
 * `[COMPANY ADDRESS]` in the Terms is a deliberate placeholder for Ronak to fill
 * with the registered company name + mailing address before launch.
 */

const CONTACT_EMAIL = "ops@6thsense.dev";
const LAST_UPDATED = "July 18, 2026";

export const legalPages = [
  {
    path: "/privacy",
    kind: "legal",
    kicker: "Legal",
    updated: LAST_UPDATED,
    title: "Privacy Policy | 6thSense",
    description:
      "How 6thSense collects, uses, stores, and protects the data captured by the synapse / Perle app — video, tactile-glove, and IMU/motion data used to build robotics training datasets.",
    h1: "Privacy Policy",
    intro:
      "This policy explains what the 6thSense capture app (\"synapse\", also distributed as \"Perle\") collects, why we collect it, where it is stored, and the choices you have. We keep it plain and specific to what we actually do — recording demonstration data for robot learning — instead of generic legal boilerplate.",
    sections: [
      {
        h2: "Who this covers",
        body: "This policy applies to the 6thSense capture app and the data it records and uploads. 6thSense builds tactile-capture hardware and software that records human demonstrations to create training datasets for dexterous robots. If you use the capture app, this policy describes how we handle the data you create with it.",
      },
      {
        h2: "What we collect",
        body: "The capture app records demonstration sessions. Depending on the hardware connected, a session can include:",
        items: [
          "Video — first-person (egocentric) RGB video, and where a depth camera is attached, per-frame depth. This can include your hands, the objects and surfaces you interact with, and whatever is in the camera's field of view.",
          "Tactile-glove data — contact and pressure signals from the sensing glove and skin (for example, contact onset and pressure over time across the sensor channels).",
          "IMU / motion data — accelerometer and gyroscope readings and derived motion cues from the rig and wearables.",
          "Session and device metadata — timestamps, device identifiers, hardware and firmware versions, capture settings, calibration values, and quality-check metrics used to align and validate the recording.",
          "Account information — if you sign in, the email address and basic account details used to authenticate you and associate sessions with your account.",
          "Basic technical logs — app version, error and diagnostic logs, and upload status used to keep capture and upload working.",
        ],
      },
      {
        h2: "What we do NOT intentionally collect",
        body: "The app is built to capture task demonstrations, not to surveil you. We do not intentionally collect precise location tracking, contacts, browsing history, or advertising identifiers. Because video captures whatever is in frame, please avoid recording bystanders or sensitive surroundings you do not intend to share, and get consent from anyone who may appear in a recording.",
      },
      {
        h2: "How we use the data",
        body: "We use the captured data to:",
        items: [
          "Build, curate, and improve robotics training datasets and the models trained on them.",
          "Align, calibrate, and quality-check recordings across video, touch, and motion so episodes are model-ready.",
          "Operate, debug, and improve the capture app and pipeline.",
          "Provide processed datasets and results to the 6thSense partners and customers those datasets are captured for.",
          "Meet legal, security, and safety obligations.",
        ],
      },
      {
        h2: "Where data is stored",
        body: [
          "Captured sessions are uploaded from the app to cloud storage hosted on Amazon Web Services (AWS), primarily Amazon S3, along with the supporting databases and services we run on AWS. Data is transmitted over encrypted connections (HTTPS/TLS) and stored on AWS infrastructure.",
          "We restrict access to captured data to the people and systems that need it to build and deliver datasets, and we rely on AWS's physical and infrastructure security for the underlying storage.",
        ],
      },
      {
        h2: "How long we keep it",
        body: "We keep captured data for as long as needed to build and support the datasets it is part of and to run our business, unless a specific agreement with a partner or customer sets a different period. When data is no longer needed, or on a valid deletion request, we delete it or remove its association with you. Note that data already incorporated into a trained model or an aggregated dataset may not be individually removable after the fact.",
      },
      {
        h2: "Third parties we share with",
        body: [
          "We do not sell your data. We share it only as needed to run the service:",
        ],
        items: [
          "Amazon Web Services (AWS) — cloud hosting and storage (Amazon S3 and related services) for uploaded sessions and our backend.",
          "Partners and customers — the specific partner or customer that a dataset is captured for, under agreement.",
          "Service providers — vetted vendors who help us operate the pipeline (for example, infrastructure and error monitoring), limited to what they need.",
          "Legal and safety — authorities when required by law, or to protect rights, safety, and security.",
        ],
      },
      {
        h2: "Security",
        body: "We use encryption in transit, access controls, and reputable cloud infrastructure to protect captured data. No system is perfectly secure, so we cannot guarantee absolute security, but we work to protect your data and to limit who can access it.",
      },
      {
        h2: "Your rights and choices",
        body: "Depending on where you live, you may have the right to access, correct, or delete your data, or to object to or restrict certain processing. You can also stop using the app and ask us to delete sessions associated with your account. To make a request, contact us at the address below and we will respond within a reasonable time.",
        contact: true,
      },
      {
        h2: "Children",
        body: "The capture app is intended for use by professionals and partners, not by children. It is not directed to anyone under 16, and we do not knowingly collect data from children.",
      },
      {
        h2: "Changes to this policy",
        body: "We may update this policy as the product evolves. When we make material changes, we will update the date at the top of this page. Continued use of the app after an update means you accept the revised policy.",
      },
      {
        h2: "Contact us",
        body: "Questions about this policy or your data? Reach us at:",
        contact: true,
      },
    ],
    related: [
      { href: "/terms", label: "Terms of Service" },
      { href: "/", label: "Home" },
    ],
  },

  {
    path: "/terms",
    kind: "legal",
    kicker: "Legal",
    updated: LAST_UPDATED,
    title: "Terms of Service | 6thSense",
    description:
      "The terms governing use of the 6thSense capture app (synapse / Perle) and services — beta software provided as-is, acceptable use, data rights, and disclaimers.",
    h1: "Terms of Service",
    intro:
      "These Terms govern your use of the 6thSense capture app (\"synapse\", also distributed as \"Perle\"), our hardware software, and related services (together, the \"Service\"). By using the Service, you agree to these Terms. If you are using the Service on behalf of an organization, you agree on its behalf.",
    sections: [
      {
        h2: "Beta software",
        body: "The Service is early-stage, actively developed software provided for evaluation and data capture. Features may change, break, or be removed, and recordings or uploads may occasionally fail. Do not rely on the Service as the only copy of anything you cannot lose.",
      },
      {
        h2: "Your account",
        body: "If the Service requires an account, you are responsible for keeping your credentials secure and for activity under your account. Tell us promptly at the contact address below if you suspect unauthorized access.",
      },
      {
        h2: "License to use the Service",
        body: "Subject to these Terms, 6thSense grants you a limited, non-exclusive, non-transferable, revocable license to use the Service to capture and upload demonstration data. You may not copy, modify, reverse engineer, resell, or attempt to extract source code from the Service except where the law expressly allows it.",
      },
      {
        h2: "Acceptable use",
        body: "You agree not to:",
        items: [
          "Use the Service to break the law or infringe anyone's rights.",
          "Record people or private spaces without the consent required where you are.",
          "Upload malware, or interfere with, overload, or attempt to gain unauthorized access to the Service or its infrastructure.",
          "Misrepresent the origin of data you capture and upload.",
        ],
      },
      {
        h2: "Data you capture",
        body: [
          "You are responsible for the recordings you create and for having the rights and consents needed to capture and upload them, including consent from anyone who appears in a recording.",
          "You grant 6thSense the rights needed to host, process, and use the data you upload to build, curate, and improve robotics training datasets and the models trained on them, and to deliver datasets and results to the partners and customers they are captured for. How we handle that data is described in our Privacy Policy.",
        ],
      },
      {
        h2: "Our intellectual property",
        body: "6thSense and its licensors own the Service, including the app, hardware software, pipeline, and trademarks. These Terms do not transfer any of those rights to you beyond the limited license above.",
      },
      {
        h2: "Disclaimer of warranties",
        body: "The Service is provided \"as is\" and \"as available,\" without warranties of any kind, whether express or implied, including fitness for a particular purpose, merchantability, and non-infringement. We do not warrant that the Service will be uninterrupted, error-free, or that any recording will be captured or preserved without loss.",
      },
      {
        h2: "Limitation of liability",
        body: "To the maximum extent permitted by law, 6thSense will not be liable for any indirect, incidental, special, consequential, or punitive damages, or for lost data, profits, or revenue, arising from your use of the Service. Our total liability for any claim relating to the Service is limited to the amount you paid us for the Service in the twelve months before the claim, or, if you paid nothing, one hundred U.S. dollars (USD 100).",
      },
      {
        h2: "Termination",
        body: "You may stop using the Service at any time. We may suspend or end your access if you violate these Terms or to protect the Service, and we may modify or discontinue the Service. Terms that by their nature should survive termination — such as data rights, disclaimers, and limitation of liability — will survive.",
      },
      {
        h2: "Changes to these Terms",
        body: "We may update these Terms as the product evolves. When we make material changes, we will update the date at the top of this page. Continued use of the Service after an update means you accept the revised Terms.",
      },
      {
        h2: "Governing law and company",
        body: "These Terms are governed by the laws applicable at the company's principal place of business, without regard to conflict-of-laws rules. The Service is provided by [COMPANY ADDRESS].",
      },
      {
        h2: "Contact us",
        body: "Questions about these Terms? Reach us at:",
        contact: true,
      },
    ],
    related: [
      { href: "/privacy", label: "Privacy Policy" },
      { href: "/", label: "Home" },
    ],
  },
];

export const legalContactEmail = CONTACT_EMAIL;

/** Lookup helper used by the React route component. */
export function getLegalPage(path) {
  return legalPages.find((p) => p.path === path) || null;
}
