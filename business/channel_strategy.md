# u2Lighter Channel Strategy

## Overview
This document outlines the go-to-market strategy for u2Lighter products across different sales channels. Each channel has distinct audience, asset requirements, unit economics, and operational considerations.

---

## Channel Definitions

### 1. Wholesale (B2B)
**Target**: Museum shops, gift stores, concept stores, boutique retailers
**Volume**: 50-500 units per order
**Lead Time**: 2-4 weeks

| Aspect | Detail |
|--------|--------|
| **Price** | COGS × 2.2 |
| **Margin** | ~55% |
| **Payment** | Net 30-60 days |
| **MOQ** | 20 units per SKU |
| **Packaging** | Bulk (plain boxes) |
| **Assets Needed** | Line sheet PDF, product photos, wholesale terms |

**Pros**: Predictable volume, lower CAC, relationship-based
**Cons**: Lower margin, payment delay, inventory risk on buyer side

**Key Accounts to Target**:
- Museum gift shops (design-focused)
- Concept stores (e.g., MOMA Design Store, Conran Shop)
- Specialty gift chains
- Corporate gifting companies

---

### 2. Direct-to-Consumer (DTC)
**Target**: End consumers via owned channels
**Volume**: 1-10 units per order
**Lead Time**: 1-3 days (print-on-demand) or 1-2 weeks (inventory)

| Aspect | Detail |
|--------|--------|
| **Price** | COGS × 5.0 |
| **Margin** | ~80% |
| **Payment** | Immediate |
| **MOQ** | 1 unit |
| **Packaging** | Branded gift box + tissue + card |
| **Assets Needed** | Product page (hero, 3-4, side), AR viewer, video, lifestyle images |

**Channels**:
- **Shopify/Website**: Full control, highest margin
- **Instagram Shop**: Visual discovery, integrated checkout
- **TikTok Shop**: Viral potential, younger demographic
- **Etsy**: Craft/design audience, built-in traffic

**Pros**: Highest margin, customer data, brand control, immediate payment
**Cons**: High CAC, marketing heavy, fulfillment complexity

**Marketing Stack**:
- Meta Ads (Facebook/Instagram) - primary acquisition
- TikTok Ads - viral content, younger audience
- Google Shopping - intent-based
- Email/SMS - retention (Klaviyo)
- Influencer/creator partnerships - UGC

---

### 3. Custom Orders (B2C/B2B)
**Target**: Individuals wanting personalized figures, corporate gifts, events
**Volume**: 1-100 units per order
**Lead Time**: 2-3 weeks (design → print → ship)

| Aspect | Detail |
|--------|--------|
| **Price** | COGS × 3.0 + €50 setup fee |
| **Margin** | ~65% (after design time) |
| **Payment** | 50% deposit, 50% on completion |
| **Assets Needed** | Custom order form, design preview, AR proof |

**Workflow**:
1. Customer submits reference images/prompt via web form
2. Meshy.ai generates 3D model → design_pack created
3. Pipeline runs → preview renders sent for approval
4. Customer approves → print → ship

**Pros**: High margin, differentiation, premium positioning
**Cons**: Manual design review, longer lead time, revision risk

**Pricing Tiers**:
- **Single Custom**: €50 setup + €35/unit (1-5 units)
- **Small Batch**: €50 setup + €30/unit (6-20 units)
- **Corporate/Event**: €100 setup + €25/unit (20+ units)

---

### 4. Print Farm / License (Future)
**Target**: Other makerspaces, print farms, international distributors
**Model**: License STL/3MF files for local printing
**Revenue**: €5-10 per print + file license fee

---

## Unit Economics Summary (Panter v1, PLA)

| Metric | Value |
|--------|-------|
| Filament | 17.5g @ €25/kg = €0.44 |
| Machine Time | 98 min @ €8/h = €13.07 |
| Packaging | €1.50 |
| Labor | €0.50 |
| **Total COGS** | **€15.51** |

| Channel | Price | Margin | Margin % | Break-even (units/mo) |
|---------|-------|--------|----------|----------------------|
| Wholesale | €34.12 | €18.61 | 55% | 387 |
| DTC | €77.55 | €62.04 | 80% | 116 |
| Custom | €96.53 | €81.02 | 84% | 89 |

*Fixed costs/month: €650 (printer €100, software €50, marketing €200, rent €300)*

---

## CAC & LTV Estimates

| Channel | CAC (est) | LTV (est) | LTV/CAC | Payback Period |
|---------|-----------|-----------|---------|----------------|
| Wholesale | €50 | €200 | 4.0x | 1 order |
| DTC (Meta) | €25 | €120 | 4.8x | 2 months |
| DTC (TikTok) | €15 | €100 | 6.7x | 1 month |
| Custom | €100 | €300 | 3.0x | 1 order |

*Assumptions*: DTC repeat rate 30%, AOV €77, wholesale reorder 2x/year

---

## Launch Checklist per Channel

### Wholesale
- [ ] Line sheet PDF (product specs, pricing, terms)
- [ ] 10+ hero lifestyle images
- [ ] Wholesale terms document (MOQ, payment, returns)
- [ ] Sample kits for key buyers
- [ ] Faire/Ankorstore listing
- [ ] Trade show calendar (Maison&Objet, Ambiente, NY Now)

### DTC - Shopify
- [ ] Product page with AR viewer
- [ ] Hero video (360° turntable)
- [ ] 3-4 hero stills (front, 3-4, side, back)
- [ ] Lifestyle images (4+ settings)
- [ ] Email capture + welcome flow
- [ ] Abandoned cart flow
- [ ] Post-purchase review request
- [ ] Google Merchant Center + Shopping ads

### DTC - Instagram/TikTok Shop
- [ ] 9:16 Reels/TikTok videos (3+ hooks)
- [ ] 1:1 carousel posts
- [ ] 4:5 portrait images
- [ ] UGC templates for creators
- [ ] Affiliate program setup
- [ ] Live shopping schedule

### Custom Orders
- [ ] Web form (image upload, prompt, options)
- [ ] Meshy.ai API integration
- [ ] Automated preview generation
- [ ] Approval workflow (email + link)
- [ ] Deposit payment link
- [ ] Production SLA (10 business days)

---

## Seasonal Calendar

| Month | Focus |
|-------|-------|
| Jan | New year desk setup, corporate gifting |
| Feb | Valentine's (custom couples figures) |
| Mar | Spring refresh, Easter |
| Apr | Mother's Day prep |
| May | Mother's Day, graduation gifts |
| Jun | Father's Day, summer desk |
| Jul | Summer vacation, travel |
| Aug | Back-to-school, office prep |
| Sep | Fall collection launch |
| Oct | Halloween, holiday prep |
| Nov | Black Friday, Christmas prep |
| Dec | Christmas, last-minute gifts |

---

## Key Metrics to Track

### Weekly
- Units printed vs. orders
- Filament inventory (kg)
- Print queue depth (hours)

### Monthly
- Revenue by channel
- CAC by channel
- LTV by cohort
- Gross margin %
- Break-even progress
- Customer NPS

### Quarterly
- New design launches
- Channel mix shift
- International expansion readiness
- Print farm capacity planning

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Filament price spike | Multi-supplier, 3-month buffer stock |
| Printer downtime | 2+ printers, maintenance schedule |
| Design copyright issues | Original designs only, clear licensing |
| Seasonal demand spikes | Pre-print popular SKUs in Q3 |
| Platform algorithm changes | Diversified channels, owned audience (email) |
| Shipping damage | Tested packaging, insurance on high-value |

---

## Next Steps
1. Finalize wholesale line sheet
2. Set up Shopify store with AR integration
3. Create TikTok/Reels content batch (10 videos)
4. Build custom order form + Meshy integration
5. Establish print farm partner for overflow