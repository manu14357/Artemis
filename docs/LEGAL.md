# ARTEMIS Legal & Compliance

> **This document is informational only and does not constitute legal advice.**
> Consult a qualified legal professional before deploying counter-UAV technology
> in any jurisdiction.

---

## 1. India — Ministry of Civil Aviation / Ministry of Home Affairs

### Drone regulations (DGCA UAS Rules 2021)
- Detection-only systems (passive listening) generally do not require DGCA clearance.
- **Active RF jamming** is a spectrum offence under the Indian Wireless Telegraphy Act,
  1933, and the Telecom Regulatory Authority of India (TRAI) framework.
  A **Ministry of Home Affairs (MHA) clearance** is required for any active RF
  countermeasure deployment.
- Physical interdiction devices require separate clearance from MHA.
- ARTEMIS ships with `SimRelay` (simulation) as default. Enabling `GPIORelay` for
  real hardware effectors is the operator's responsibility to license.

### Operator checklist
- [ ] Obtain MHA/state authority permission before enabling active jammers.
- [ ] Register site with local aviation authority if within ATZ / CTR airspace.
- [ ] Maintain engagement log (`logs/engagements.ndjson`) for audit purposes.

---

## 2. United States — FCC / FAA

### FCC Part 97 / Part 15
- Passive RF monitoring is lawful under Part 15 provided the receiver does not
  retransmit signals.
- **Jamming of UAV control links is prohibited** under 47 U.S.C. § 333 (Communications
  Act) and enforced by the FCC. Violations carry civil penalties up to $100,000/day
  and criminal penalties.
- Federal law enforcement agencies (DHS, DOJ, DoD) have statutory exceptions under
  the Preventing Emerging Threats Act (2018).

### FAA UAS remote ID
- ARTEMIS detection output is compatible with FAA Remote ID broadcast detection,
  but is not a certified Remote ID display application.

---

## 3. European Union — GDPR / EASA

### GDPR (Regulation (EU) 2016/679)
- Acoustic sensors that incidentally capture voice conversations may constitute
  processing of personal data. Depending on deployment location, this could require:
  - A Data Protection Impact Assessment (DPIA) under Art. 35.
  - A lawful basis for processing (Art. 6), typically legitimate interests or
    public security task.
- Audio data should be processed only for drone-detection purposes and discarded
  immediately (ARTEMIS does not persist raw audio by default).

### EASA Implementing Regulation (EU) 2019/947
- Passive detection of UA in protected zones is generally permitted.
- Command-and-control link jamming is not addressed by EASA and falls under
  national spectrum law (member-state responsibility).

---

## 4. Acoustic Privacy

- ARTEMIS uses a 500 ms sliding window; voice-class events are not retained.
- The acoustic model classifies only four classes: `drone`, `bird`, `wind`, `ambient`.
- Operators deploying nodes near residential areas should:
  - Post visible notice of acoustic monitoring.
  - Disable acoustic recording to disk (disabled by default; the pipeline discards
    raw audio after classification).

---

## 5. Responsible Use Checklist

Before any deployment, the operator must confirm:

- [ ] All applicable national and local UAV counter-measure regulations reviewed.
- [ ] Active effectors (jammers, nets) are either disabled or properly licensed.
- [ ] Site-owner / authority authorisation obtained in writing.
- [ ] Data retention policy documented; logs rotated per local requirements.
- [ ] GDPR/privacy impact assessed for acoustic sensor in populated areas.
- [ ] Engagement log path (`logs/engagements.ndjson`) is preserved and tamper-evident.
- [ ] Security credentials (MQTT username/password, API JWT secret) are changed from defaults.

---

## 6. Export Control

This software does not include encryption above EAR99 thresholds and is not
subject to US EAR dual-use export controls as a counter-UAV detection system.
However, physical hardware components (radar, RF jammers) may be subject to
ITAR/EAR restrictions depending on jurisdiction. Consult export counsel before
shipping hardware internationally.

---

## 7. Disclaimer

ARTEMIS is provided "as is" without warranty. The contributors accept no
liability for any consequence arising from deployment, including but not limited
to aviation incidents, regulatory penalties, or property damage. Operators bear
sole responsibility for lawful use.
