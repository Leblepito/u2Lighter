-- u2Lighter Custom Order Automation - Supabase Schema
-- Run this in Supabase SQL Editor

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- ORDERS TABLE
-- ============================================================================
CREATE TABLE orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id TEXT UNIQUE NOT NULL, -- Human-readable: ORD-A1B2C3D4
    customer_email TEXT NOT NULL,
    input_method TEXT NOT NULL CHECK (input_method IN ('image', 'prompt')),
    prompt TEXT,
    image_b64 TEXT, -- Base64 encoded reference image (optional, can be large)
    ref_images_b64 JSONB DEFAULT '[]'::jsonb, -- Array of base64 images
    style TEXT DEFAULT 'panter',
    plinth_color TEXT DEFAULT 'Pembe' CHECK (plinth_color IN ('Pembe', 'Siyah', 'Fildisi', 'Sari')),
    pins TEXT DEFAULT '8,4,2',
    plinth_height TEXT DEFAULT '3.0',
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending',      -- Order received, not yet processed
        'processing',   -- Meshy API called, waiting for model
        'queued',       -- Model ready, GitHub Actions triggered
        'printing',     -- Pipeline running (geometry + render)
        'delivered',    -- Success! Customer notified with links
        'failed'        -- Error occurred
    )),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    design_pack_path TEXT, -- Path to design_pack JSON
    meshy_task_id TEXT,    -- Meshy.ai async task ID
    meshy_model_url TEXT,  -- Download URL for generated model
    github_run_id BIGINT,  -- GitHub Actions run ID
    error_message TEXT,    -- Error details if failed
    cost_estimate_eur NUMERIC(10, 2), -- Estimated production cost
    metadata JSONB DEFAULT '{}'::jsonb -- Flexible extra data
);

-- Indexes for orders
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_customer_email ON orders(customer_email);
CREATE INDEX idx_orders_created_at ON orders(created_at DESC);
CREATE INDEX idx_orders_order_id ON orders(order_id);

-- Updated_at trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_orders_updated_at
    BEFORE UPDATE ON orders
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- ============================================================================
-- DESIGN_PACKS TABLE
-- ============================================================================
CREATE TABLE design_packs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    figure_id TEXT NOT NULL, -- e.g., "custom_ORD-A1B2C3D4"
    design_pack JSONB NOT NULL, -- Full design_pack JSON
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    version INTEGER DEFAULT 1
);

CREATE INDEX idx_design_packs_order_id ON design_packs(order_id);
CREATE INDEX idx_design_packs_figure_id ON design_packs(figure_id);

-- ============================================================================
-- ASSETS TABLE
-- ============================================================================
CREATE TABLE assets (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    asset_type TEXT NOT NULL CHECK (asset_type IN (
        'model_3mf', 'model_glb', 'model_usdz', 'model_stl',
        'video_mp4', 'video_preview', 'stills', 'contact_sheet',
        'viewer_html', 'qr_code', 'variant_comparison'
    )),
    file_path TEXT, -- Relative path in storage
    file_size BIGINT,
    mime_type TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_assets_order_id ON assets(order_id);
CREATE INDEX idx_assets_type ON assets(asset_type);

-- ============================================================================
-- NOTIFICATIONS TABLE
-- ============================================================================
CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    channel TEXT NOT NULL CHECK (channel IN ('email', 'webhook', 'sms', 'push')),
    recipient TEXT NOT NULL,
    subject TEXT,
    body TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed', 'bounced')),
    sent_at TIMESTAMPTZ,
    error_message TEXT,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notifications_order_id ON notifications(order_id);
CREATE INDEX idx_notifications_status ON notifications(status);

-- ============================================================================
-- COST_TRACKING TABLE
-- ============================================================================
CREATE TABLE cost_tracking (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id UUID NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    cost_category TEXT NOT NULL CHECK (cost_category IN (
        'meshy_credits', 'filament', 'machine_time', 'packaging', 'shipping', 'labor'
    )),
    amount_eur NUMERIC(10, 4) NOT NULL,
    quantity NUMERIC(10, 2), -- e.g., filament grams, machine minutes
    unit TEXT, -- 'credits', 'grams', 'minutes', 'units'
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cost_tracking_order_id ON cost_tracking(order_id);

-- ============================================================================
-- VIEW: ORDER_SUMMARY
-- ============================================================================
CREATE VIEW order_summary AS
SELECT
    o.id,
    o.order_id,
    o.customer_email,
    o.status,
    o.style,
    o.plinth_color,
    o.pins,
    o.created_at,
    o.completed_at,
    o.github_run_id,
    o.cost_estimate_eur,
    COALESCE(SUM(ct.amount_eur), 0) AS actual_cost_eur,
    COUNT(a.id) AS asset_count,
    COUNT(n.id) FILTER (WHERE n.status = 'sent') AS notifications_sent
FROM orders o
LEFT JOIN cost_tracking ct ON ct.order_id = o.id
LEFT JOIN assets a ON a.order_id = o.id
LEFT JOIN notifications n ON n.order_id = o.id
GROUP BY o.id;

-- ============================================================================
-- ROW LEVEL SECURITY (RLS)
-- ============================================================================
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE design_packs ENABLE ROW LEVEL SECURITY;
ALTER TABLE assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE cost_tracking ENABLE ROW LEVEL SECURITY;

-- Policies: Users can only see their own orders (by email)
-- Note: In production, use Supabase Auth with JWT claims
CREATE POLICY "Users can view own orders" ON orders
    FOR SELECT USING (customer_email = auth.jwt() ->> 'email');

CREATE POLICY "Users can insert own orders" ON orders
    FOR INSERT WITH CHECK (customer_email = auth.jwt() ->> 'email');

-- Service role can do everything (for webhook handlers)
CREATE POLICY "Service role full access" ON orders
    FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- Repeat for other tables
CREATE POLICY "Service role full access" ON design_packs FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');
CREATE POLICY "Service role full access" ON assets FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');
CREATE POLICY "Service role full access" ON notifications FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');
CREATE POLICY "Service role full access" ON cost_tracking FOR ALL USING (auth.jwt() ->> 'role' = 'service_role');

-- ============================================================================
-- STORAGE BUCKETS (create via Supabase Dashboard or CLI)
-- ============================================================================
-- Buckets needed:
-- 1. order-assets (private) - stores 3MF, GLB, USDZ, STL, videos, images
-- 2. design-packs (private) - stores design_pack JSON files
-- 3. marketing-assets (public) - stores viewer.html, QR codes for CDN

-- Example storage policies (run in Supabase Dashboard):
-- CREATE POLICY "Users can upload own order assets" ON storage.objects
--   FOR INSERT WITH CHECK (
--     bucket_id = 'order-assets' AND
--     (storage.foldername(name))[1] = auth.uid()::text
--   );
--
-- CREATE POLICY "Users can view own order assets" ON storage.objects
--   FOR SELECT USING (
--     bucket_id = 'order-assets' AND
--     (storage.foldername(name))[1] = auth.uid()::text
--   );

-- ============================================================================
-- HELPER FUNCTIONS
-- ============================================================================

-- Generate human-readable order ID
CREATE OR REPLACE FUNCTION generate_order_id()
RETURNS TEXT AS $$
DECLARE
    new_id TEXT;
BEGIN
    LOOP
        new_id := 'ORD-' || UPPER(SUBSTRING(MD5(RANDOM()::TEXT || CLOCK_TIMESTAMP()::TEXT) FROM 1 FOR 8));
        IF NOT EXISTS (SELECT 1 FROM orders WHERE order_id = new_id) THEN
            RETURN new_id;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Auto-set order_id on insert
CREATE OR REPLACE FUNCTION set_order_id()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.order_id IS NULL OR NEW.order_id = '' THEN
        NEW.order_id := generate_order_id();
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_set_order_id
    BEFORE INSERT ON orders
    FOR EACH ROW
    EXECUTE FUNCTION set_order_id();

-- ============================================================================
-- SAMPLE QUERIES
-- ============================================================================

-- Get all pending orders with details
-- SELECT * FROM order_summary WHERE status IN ('pending', 'processing', 'queued');

-- Get total revenue by month
-- SELECT DATE_TRUNC('month', created_at) AS month, COUNT(*) as orders, SUM(cost_estimate_eur) as revenue
-- FROM orders WHERE status = 'delivered' GROUP BY month ORDER BY month DESC;

-- Get average production cost
-- SELECT AVG(cost_estimate_eur) FROM orders WHERE status = 'delivered';

-- Get failed orders with errors
-- SELECT order_id, customer_email, error_message, created_at FROM orders WHERE status = 'failed';

-- Get orders by style
-- SELECT style, COUNT(*) FROM orders GROUP BY style ORDER BY COUNT(*) DESC;