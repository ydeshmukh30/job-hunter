# Keyword map — Customer Success Manager

ATS matching is string-based. Every term below is lifted verbatim from the JD; the second
column says which document already carries it. Terms marked `_not yet covered_` are real
gaps — close them in `gap-analysis.md` before applying.

Backticked terms in the first column are what `scripts/jd_match.py` reads:

```bash
scripts/jd_match.py roles/customer-success-manager/keyword-map.md ~/Downloads/some-jd.txt
```

| Keyword | Covered in |
|---|---|
| `customer success manager` | resume.md (title), linkedin.md, cover-letter.md |
| `customer success` | resume.md, linkedin.md |
| `client retention` | resume.md, star-stories.md |
| `retention` | resume.md, cover-letter.md |
| `customer satisfaction` | resume.md, star-stories.md |
| `account management` | resume.md, linkedin.md |
| `enterprise` | resume.md (current title), linkedin.md |
| `key customers` | resume.md |
| `primary contact` | resume.md, star-stories.md |
| `onboarding` | resume.md, star-stories.md, cover-letter.md |
| `product adoption` | resume.md |
| `adoption` | resume.md, cover-letter.md |
| `training` | resume.md (saasguru title), star-stories.md |
| `business reviews` | resume.md |
| `escalations` | resume.md, star-stories.md |
| `health metrics` | resume.md |
| `KPIs` | resume.md, profile-source.md |
| `customer data` | resume.md |
| `usage trends` | _not yet covered_ |
| `reporting` | resume.md |
| `stakeholder` | resume.md, star-stories.md |
| `cross-functional` | resume.md, star-stories.md |
| `product management` | resume.md, star-stories.md |
| `customer advocacy` | resume.md |
| `upselling` | _not yet covered_ |
| `cross-selling` | _not yet covered_ |
| `negotiation` | resume.md (JSM), star-stories.md |
| `conflict resolution` | star-stories.md |
| `problem-solving` | resume.md, linkedin.md |
| `critical thinking` | _not yet covered_ |
| `time management` | resume.md |
| `SaaS` | resume.md, linkedin.md, cover-letter.md |
| `B2B` | _not yet covered_ |
| `CRM` | _not yet covered_ — `[[NEED: which CRM]]` |
| `Salesforce` | _not yet covered_ — `[[NEED]]` |
| `HubSpot` | _not yet covered_ — `[[NEED]]` |
| `Gainsight` | _not yet covered_ — `[[NEED]]` |
| `ChurnZero` | _not yet covered_ — `[[NEED]]` |
| `customer success platform` | _not yet covered_ — `[[NEED]]` |
| `data analytics` | resume.md |
| `NPS` | resume.md, profile-source.md |
| `customer lifecycle` | resume.md |
| `customer success strategies` | resume.md, cover-letter.md |
| `SOP` | resume.md, star-stories.md |
| `MBA` | resume.md, linkedin.md |

## Coverage

**39 of 45 covered (86.7%).** The six open terms fall into two groups:

1. **Tooling** — CRM, Salesforce, HubSpot, Gainsight, ChurnZero, customer success
   platform. Cannot be closed without Vanshika confirming what she has actually used.
   This is the highest-value gap: tool names are the most literally string-matched terms
   in any ATS.
2. **Revenue motion** — upselling, cross-selling, B2B, usage trends, critical thinking.
   Almost certainly true of her current enterprise role but not stated anywhere on the
   profile. Cheap to close with one conversation.
