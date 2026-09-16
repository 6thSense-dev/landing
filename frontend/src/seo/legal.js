/**
 * Legal-page content manifest — single source of truth for public legal routes.
 *
 * Mirrors the shape of productPages in ./pages.js so it can reuse the SAME
 * build-time prerender (scripts/seoPrerenderPlugin.js → crawlable static
 * dist/<path>/index.html) and the same light-paper layout (src/pages/product.css).
 *
 * These pages are load-bearing. /privacy/synapse is the store policy for the
 * LAN controller app; /privacy covers the separate account/cloud capture
 * service. Do not merge their materially different data flows.
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
const SYNAPSE_LAST_UPDATED = "September 15, 2026";

export const legalPages = [
  {
    path: "/privacy/synapse",
    kind: "legal",
    kicker: "Legal",
    updated: SYNAPSE_LAST_UPDATED,
    title: "Synapse Privacy Policy | 6thSense",
    description:
      "How 6thSense Synapse handles local-network camera data, app-local settings, recording playback and export, optional analytics, and software updates.",
    h1: "Synapse Privacy Policy",
    intro:
      "Synapse is a mobile control plane for compatible egocentric capture rigs and cameras. Camera controls work without an account. Where enabled, an optional contributor account connects to a separate cloud service for supervised data contributions and payments. Capture devices remain the primary storage for local recordings; Synapse communicates with them over the local network, sends usage analytics only after affirmative consent, and contacts software-update services as described below.",
    sections: [
      {
        h2: "Camera and recording data",
        body: [
          "Synapse reads device status, identifiers, diagnostics, recording metadata, previews, and footage from compatible cameras over the local network. Recordings are created and retained by the camera.",
          "When you play footage, the camera streams it through the app. When you export a recording, Synapse temporarily downloads the selected file into its private cache and opens the system share sheet. The destination you choose controls any resulting copy. Synapse does not request access to your photo library.",
        ],
      },
      {
        h2: "Data stored on this phone",
        body: [
          "Synapse may store camera IP addresses, device identifiers and nicknames, app settings, analytics consent, recent onboarding network names, an opaque installation identifier, and an optional camera access token. This data stays in the app's local storage.",
          "Uninstalling Synapse removes that app-local data, but it does not delete recordings on cameras or copies previously shared to another app or service.",
        ],
      },
      {
        h2: "Wi-Fi credentials",
        body: "Wi-Fi passwords used while onboarding a camera are held only in memory for the active setup session. They are sent directly to the camera over the local network, cleared when the session ends or the app backgrounds, and never included in analytics.",
      },
      {
        h2: "Optional usage analytics",
        body: [
          "Synapse sends no usage analytics unless you affirmatively consent. If you consent, the app sends product-interaction events and an opaque installation identifier to PostHog so 6thSense can understand feature use and improve reliability.",
          "These events do not include video, audio, still images, recording contents, filenames, Wi-Fi passwords, camera access tokens, or an account identity. Synapse does not use this data for advertising or cross-app tracking. You can disable analytics at any time in Settings to stop future sending.",
        ],
      },
      {
        h2: "Software and camera updates",
        body: "Synapse uses Expo Updates to check 6thSense's configured app-update service. It may also contact a configured HTTPS manifest and download endpoint to retrieve camera software. These requests transmit standard network information such as IP address and user agent to the receiving service. Camera software is cached privately before it is sent to a selected camera over the local network.",
      },
      {
        h2: "Permissions",
        body: "Synapse requests only the access needed for its current features:",
        items: [
          "Local network — find and communicate with compatible cameras.",
          "Internet and network state — reach update services, optional contributor authentication and cloud services, and, after consent, PostHog; determine whether camera networking is available.",
          "Location while in use on iOS — read the current Wi-Fi network name during camera setup. Apple gates Wi-Fi-name access behind this permission. Synapse does not use it to determine or transmit geographic location.",
          "Notifications — show an immediate local alert when a capture finishes saving. Synapse does not register for marketing notifications or remote push messages.",
        ],
      },
      {
        h2: "Accounts, advertising, and sharing",
        items: [
          "Camera controls require no login. The optional contributor service uses a separate account and regional participation agreements.",
          "Synapse contains no advertising network and does not sell or rent data.",
          "Synapse does not build advertising profiles or use analytics for tracking.",
          "6thSense receives the consented analytics described above. Outside the contributor service described below, camera and recording data is exchanged between the phone, the compatible camera, and destinations you explicitly choose.",
        ],
      },
      {
        h2: "Optional contributor accounts and cloud data",
        body: [
          "Where contributor enrollment is enabled, account authentication uses Amazon Cognito, including your phone number, verification status, and regional routing information. The contributor service stores your name, agreement receipts, operator-confirmed camera assignments, footage and review metadata, and payment records. Sign-in credentials and a deletion-status receipt may be kept in secure storage on this phone.",
          "Bank details you submit are sent over HTTPS through the contributor service to Wise for recipient setup. The app shows a masked account summary. Recipient creation does not authorize a payment; an operator separately verifies assignments, footage, and payments. In the supervised pilot, an operator imports recordings from the camera storage card; creating an account does not upload footage from your phone.",
          "Regional notices and agreements explain the collection, sharing, international transfers, and retention that apply to participation. Enrollment stays unavailable where the required final documents have not been published. This public policy does not replace those agreements.",
        ],
      },
      {
        h2: "Deleting a contributor account",
        body: [
          "Use Delete account in the contributor account area, including before enrollment or agreement acceptance. The service records the request and stops new contributor activity and approvals. Deletion may require operator work; a request or deactivation is not confirmation that data has been erased. The app displays request status and any configured completion estimate, and keeps a private status receipt so you can check completion after the login has been removed.",
          "Completion requires removal of the Cognito login, scrubbing of the contributor profile and bank summary, and an operator record of footage and processor cleanup. Any legal or payment records that must be retained require a recorded scope, reason, and review date. The applicable regional documents describe retention; this policy does not promise a fixed deletion period. Deleting the cloud account does not erase independent copies on your camera or previously shared destinations.",
        ],
      },
      {
        h2: "Your choices",
        items: [
          "Decline or disable analytics in Synapse Settings.",
          "Decline or revoke iOS location permission and enter the Wi-Fi name manually.",
          "Decline notification permission; capture controls continue to work without the local alert.",
          "Remove app-local settings by uninstalling Synapse.",
          "Contact 6thSense about previously sent consented analytics.",
        ],
        contact: true,
      },
      {
        h2: "Children",
        body: "Synapse is an operations tool for robotics data collection. It is not directed at children, and 6thSense does not knowingly collect data from children under 13 through Synapse.",
      },
      {
        h2: "Changes and contact",
        body: "If this policy changes materially, 6thSense will update this page and the date above. Questions about Synapse privacy can be sent to:",
        contact: true,
      },
    ],
    related: [
      { href: "/privacy", label: "6thSense Service Privacy Policy" },
      { href: "/terms", label: "Terms of Service" },
      { href: "/", label: "Home" },
    ],
  },

  {
    path: "/privacy",
    kind: "legal",
    kicker: "Legal",
    updated: SYNAPSE_LAST_UPDATED,
    title: "Privacy Policy | 6thSense",
    description:
      "How 6thSense collects, uses, stores, and protects the data captured by the synapse / Perle app — video, tactile-glove, and IMU/motion data used to build robotics training datasets.",
    h1: "Privacy Policy",
    intro:
      "This policy covers the 6thSense cloud contribution service and recordings submitted for robotics data collection. Synapse camera controls work without an account; optional contributor accounts and cloud submissions have additional data flows described here and in the applicable regional agreements.",
    sections: [
      {
        h2: "Who this covers",
        body: "This policy applies to the cloud contribution service and submitted recordings. 6thSense builds tactile-capture hardware and software that records human demonstrations for robotics datasets. The separate Synapse Privacy Policy covers local camera control, optional analytics, and app updates. Participation also requires the published agreements for the applicable region.",
      },
      {
        h2: "What we collect",
        body: "The capture app records demonstration sessions. Depending on the hardware connected, a session can include:",
        items: [
          "Video — first-person (egocentric) RGB video, and where a depth camera is attached, per-frame depth. This can include your hands, the objects and surfaces you interact with, and whatever is in the camera's field of view.",
          "Tactile-glove data — contact and pressure signals from the sensing glove and skin (for example, contact onset and pressure over time across the sensor channels).",
          "IMU / motion data — accelerometer and gyroscope readings and derived motion cues from the rig and wearables.",
          "Session and device metadata — timestamps, device identifiers, hardware and firmware versions, capture settings, calibration values, and quality-check metrics used to align and validate the recording.",
          "Contributor account information — your name, phone-based authentication and verification information, regional routing, agreement receipts, supervised camera assignments, and footage and payment records. Bank recipient setup uses Wise; the service keeps a masked bank summary and recipient identifiers.",
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
          "Submitted recordings are stored in cloud storage hosted on Amazon Web Services (AWS), including Amazon S3 and supporting databases. In the supervised contributor pilot, an operator imports camera storage cards; registering or signing in on the phone does not upload footage. Contributor API requests use HTTPS, and account authentication uses Amazon Cognito.",
          "We restrict access to captured data to the people and systems that need it to build and deliver datasets, and we rely on AWS's physical and infrastructure security for the underlying storage.",
        ],
      },
      {
        h2: "How long we keep it",
        body: "The applicable regional notices and agreements describe retention for contributed data. Account deletion is an operator-supervised process that records footage and processor cleanup separately from any legally required retention of consent or payment records. Retained records require a documented scope, reason, and review date. This page does not establish a fixed retention or deletion period.",
      },
      {
        h2: "Third parties we share with",
        body: [
          "We do not sell your data. We share it only as needed to run the service:",
        ],
        items: [
          "Amazon Web Services (AWS) — Cognito account authentication, cloud hosting, and storage for submitted recordings and supporting services.",
          "Wise — bank recipient setup and operator-approved payments for participating contributors.",
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
        body: "Depending on where you live, you may have rights to access, correct, or delete your data, or restrict certain processing. Use Delete account in the contributor area to initiate account deletion, including before enrollment. The request stops new contributions and approvals; it is not itself confirmation of erasure. The app retains a private receipt for checking status after login removal. Required legal or payment retention is recorded separately, and camera-local or independently shared copies are outside the cloud account deletion process.",
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
