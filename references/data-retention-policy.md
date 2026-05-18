# Genesis Education Solutions — Data Retention Policy
**Version:** 1.0 | **Effective:** May 19, 2026 | **Owner:** Shane Reynolds, COO

---

## 1. Scope

This policy covers all user data collected and stored by the Genesis Education Solutions platform (`genesis-lms--genesis-modularity.us-central1.hosted.app`) operated by Genesis K-12 Academy.

---

## 2. Data We Collect

| Data Type | Where Stored | Purpose |
|---|---|---|
| Email address | Firebase Auth | Account authentication only |
| Display name | Firebase Auth | Personalized greeting |
| User profile | Firestore `/users/{uid}` | Preferences, display settings |
| Lesson progress | Firestore `/progress/{uid}/lessons/{lessonId}` | Track completion, resume lessons |
| AI tutor conversations | Not stored — in-memory per session only | Study assistance |
| Course content (lessons) | Firestore `/lessons/` | Curriculum delivery |
| Uploaded images | Firebase Storage `/images/` | Lesson content |

---

## 3. Retention Periods

| Data Type | Retention Period | Deletion Trigger |
|---|---|---|
| Firebase Auth account | Until account deletion request | User or parent requests deletion |
| User profile | Until account deletion request | User or parent requests deletion |
| Lesson progress | 2 years from last activity | Inactivity or account deletion |
| AI tutor conversations | 0 — not persisted | Not applicable |
| Course content | Indefinite — curriculum asset | Manual admin action only |
| Uploaded images | Indefinite while course is active | Manual admin action only |

---

## 4. COPPA Compliance (Under-13 Users)

Genesis K-12 Academy serves middle school students, some of whom may be under 13 years of age. In compliance with the Children's Online Privacy Protection Act (COPPA):

- **Account creation** requires a parent or guardian to create the account on behalf of their child. Students do not self-register.
- **No behavioral advertising** or third-party tracking is used on the platform.
- **No PII beyond email** is collected for authentication.
- **AI tutor sessions** are not logged or stored. Conversations exist only in the browser session.
- **Parental access:** Parents may request a copy of their child's data or deletion of their child's account by contacting `shane@gk12academy.com`.

> **Note:** A parent-linked account flow with in-app consent capture is planned pre-launch. Until implemented, parental consent is managed through the enrollment process.

---

## 5. Data Deletion Requests

To request deletion of a student account and all associated data:

1. Email `shane@gk12academy.com` with subject: "Data Deletion Request"
2. Include the student's account email address
3. Requests will be fulfilled within **30 days**

Manual deletion steps (admin):
1. Delete Firebase Auth user record
2. Delete Firestore `/users/{uid}` document
3. Delete Firestore `/progress/{uid}` collection
4. (Optional) Remove profile image from Storage if any

---

## 6. Data Security

- All data in transit is encrypted via TLS (Firebase / Google infrastructure)
- Firestore security rules enforce owner-only access to progress and profile data
- No student can read another student's data
- Admin access is restricted to `shane@gk12academy.com` and `ethan@gk12academy.com`
- Platform API access requires a secret key stored in Google Secret Manager

---

## 7. Third-Party Services

| Service | Data Shared | Purpose |
|---|---|---|
| Google Firebase (Auth, Firestore, Storage, Hosting) | Auth tokens, lesson content, progress | Platform infrastructure |
| Google Gemini API | Lesson content excerpt (first 4000 chars) + student message | AI tutor responses |
| GitHub | Source code only — no user data | Version control / CI/CD |

Gemini API note: student messages sent to the AI tutor are processed by Google's Gemini API per Google's [AI/ML Privacy Policy](https://policies.google.com/privacy). No conversation history is sent from our servers — only the current message and lesson context.

---

## 8. Policy Updates

This policy will be reviewed before the August 2026 platform launch and updated as features are added. Changes will be communicated to enrolled families via email.

*Contact: shane@gk12academy.com*
