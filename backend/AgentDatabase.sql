-- ==========================================================================
-- Agent database for the Automated Database Scheduler
-- (accounting/agent_db_scheduler.py). Same as `python manage.py setup_agent_db`
-- with the default names AGENT_DB_NAME=Airline_Agent, AGENT_DB_TABLE=Agent_ticket_data.
-- Only the Agent's data - the status of each row is logged in the accounting
-- database: dbo.Agent_DB_Ticket_Log (Schema.sql).
-- ==========================================================================
IF DB_ID('Airline_Agent') IS NULL
    CREATE DATABASE [Airline_Agent];
GO

USE [Airline_Agent];
GO

-- Agent airline tickets - one row per passenger, only the Agent's data.
-- Insert every passenger of one invoice in ONE transaction. What happened
-- to each row is logged in the accounting database (dbo.Agent_DB_Ticket_Log).
IF OBJECT_ID('dbo.[Agent_ticket_data]', 'U') IS NULL
CREATE TABLE dbo.[Agent_ticket_data] (
    agent_row_id        BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT pk_Agent_ticket_data PRIMARY KEY,
    created_at          DATETIME2      NOT NULL CONSTRAINT df_Agent_ticket_data_created DEFAULT SYSUTCDATETIME(),
    -- API parameters - invoice (repeated on every passenger row of the invoice)
    company_id          INT            NOT NULL,
    [booking_status]     NVARCHAR(100)  NULL,
    [booking_type]       NVARCHAR(100)  NULL,
    [customer_id]        NVARCHAR(100)  NULL,
    [travel_type]        NVARCHAR(100)  NULL,
    [user_name]          NVARCHAR(200)  NULL,
    [booking_given_by]   NVARCHAR(100)  NULL,
    [booking_reference]  NVARCHAR(100)  NULL,
    [booking_ref_date]   NVARCHAR(100)  NULL,
    [airline_pnr]        NVARCHAR(100)  NULL,
    [gds_pnr]            NVARCHAR(100)  NULL,
    [payment_mode]       NVARCHAR(100)  NULL,
    [gateway_ref]        NVARCHAR(100)  NULL,
    [fop]                NVARCHAR(100)  NULL,
    [card_number]        NVARCHAR(100)  NULL,
    [parent_pnr]         NVARCHAR(100)  NULL,
    -- API parameters - passenger
    [ticket_no]          NVARCHAR(100)  NULL,
    [pax_name]           NVARCHAR(100)  NULL,
    [pax_type]           NVARCHAR(100)  NULL,
    [airline_category]   NVARCHAR(100)  NULL,
    [sector]             NVARCHAR(400)  NULL,
    [airline_code]       NVARCHAR(400)  NULL,
    [travel_date]        NVARCHAR(400)  NULL,
    [flight_no]          NVARCHAR(400)  NULL,
    [cabin]              NVARCHAR(400)  NULL,
    [class]              NVARCHAR(400)  NULL,
    [fare_type]          NVARCHAR(400)  NULL,
    [office_id]          NVARCHAR(100)  NULL,
    [emd_ticket_no_baggage] NVARCHAR(100)  NULL,
    [emd_ticket_no_meal] NVARCHAR(100)  NULL,
    [emd_ticket_no_seat] NVARCHAR(100)  NULL,
    [emd_ticket_no_other_ssr] NVARCHAR(100)  NULL,
    [ssr_baggage_details] NVARCHAR(100)  NULL,
    [ssr_meal_details]   NVARCHAR(100)  NULL,
    [ssr_seat_details]   NVARCHAR(100)  NULL,
    [ssr_other_details]  NVARCHAR(100)  NULL,
    -- API parameters - amounts (NULL = "")
    [basic_fare]                 DECIMAL(18,2)  NULL,
    [yq_tax]                     DECIMAL(18,2)  NULL,
    [yr_tax]                     DECIMAL(18,2)  NULL,
    [k3_tax]                     DECIMAL(18,2)  NULL,
    [tax_others]                 DECIMAL(18,2)  NULL,
    [seat_charges]               DECIMAL(18,2)  NULL,
    [meal_charges]               DECIMAL(18,2)  NULL,
    [baggage_charges]            DECIMAL(18,2)  NULL,
    [other_ssr]                  DECIMAL(18,2)  NULL,
    [cust_discount_amount]       DECIMAL(18,2)  NULL,
    [cust_tds_amount]            DECIMAL(18,2)  NULL,
    [cust_markup]                DECIMAL(18,2)  NULL,
    [cust_addl_markup]           DECIMAL(18,2)  NULL,
    [cust_ssr_markup]            DECIMAL(18,2)  NULL,
    [cust_service_fee]           DECIMAL(18,2)  NULL,
    [cust_addl_service_fee]      DECIMAL(18,2)  NULL,
    [cust_ssr_service_fee]       DECIMAL(18,2)  NULL,
    [cust_service_fee_gst]       DECIMAL(18,2)  NULL,
    [cust_ssr_service_fee_gst]   DECIMAL(18,2)  NULL,
    [cust_addl_service_fee_gst]  DECIMAL(18,2)  NULL,
    [supp_commission_amount]     DECIMAL(18,2)  NULL,
    [supp_tds_amount]            DECIMAL(18,2)  NULL,
    [supp_markup]                DECIMAL(18,2)  NULL,
    [supp_addl_markup]           DECIMAL(18,2)  NULL,
    [supp_ssr_markup]            DECIMAL(18,2)  NULL,
    [supp_service_fee]           DECIMAL(18,2)  NULL,
    [supp_addl_service_fee]      DECIMAL(18,2)  NULL,
    [supp_ssr_service_fee]       DECIMAL(18,2)  NULL,
    [supp_service_fee_gst]       DECIMAL(18,2)  NULL,
    [supp_ssr_service_fee_gst]   DECIMAL(18,2)  NULL,
    [supp_addl_service_fee_gst]  DECIMAL(18,2)  NULL,
    [supplier_penalty]           DECIMAL(18,2)  NULL,
    [agent_penalty]              DECIMAL(18,2)  NULL,
    [penalty_amount]             DECIMAL(18,2)  NULL,
    [cust_markup_reversal]       DECIMAL(18,2)  NULL,
    [cust_addl_markup_reversal]  DECIMAL(18,2)  NULL,
    [cust_ssr_markup_reversal]   DECIMAL(18,2)  NULL,
    [supp_markup_reversal]       DECIMAL(18,2)  NULL,
    [supp_addl_markup_reversal]  DECIMAL(18,2)  NULL,
    [supp_ssr_markup_reversal]   DECIMAL(18,2)  NULL
);
GO
-- Columns added to / removed from the API after the table was created (safe to run again)
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'booking_status') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [booking_status] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'booking_type') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [booking_type] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'customer_id') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [customer_id] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'travel_type') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [travel_type] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'user_name') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [user_name] NVARCHAR(200) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'booking_given_by') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [booking_given_by] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'booking_reference') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [booking_reference] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'booking_ref_date') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [booking_ref_date] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'airline_pnr') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [airline_pnr] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'gds_pnr') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [gds_pnr] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'payment_mode') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [payment_mode] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'gateway_ref') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [gateway_ref] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'fop') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [fop] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'card_number') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [card_number] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'parent_pnr') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [parent_pnr] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'ticket_no') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [ticket_no] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'pax_name') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [pax_name] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'pax_type') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [pax_type] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'airline_category') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [airline_category] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'sector') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [sector] NVARCHAR(400) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'airline_code') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [airline_code] NVARCHAR(400) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'travel_date') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [travel_date] NVARCHAR(400) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'flight_no') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [flight_no] NVARCHAR(400) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cabin') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cabin] NVARCHAR(400) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'class') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [class] NVARCHAR(400) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'fare_type') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [fare_type] NVARCHAR(400) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'office_id') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [office_id] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'emd_ticket_no_baggage') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [emd_ticket_no_baggage] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'emd_ticket_no_meal') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [emd_ticket_no_meal] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'emd_ticket_no_seat') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [emd_ticket_no_seat] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'emd_ticket_no_other_ssr') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [emd_ticket_no_other_ssr] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'ssr_baggage_details') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [ssr_baggage_details] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'ssr_meal_details') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [ssr_meal_details] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'ssr_seat_details') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [ssr_seat_details] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'ssr_other_details') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [ssr_other_details] NVARCHAR(100) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'basic_fare') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [basic_fare] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'yq_tax') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [yq_tax] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'yr_tax') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [yr_tax] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'k3_tax') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [k3_tax] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'tax_others') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [tax_others] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'seat_charges') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [seat_charges] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'meal_charges') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [meal_charges] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'baggage_charges') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [baggage_charges] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'other_ssr') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [other_ssr] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cust_discount_amount') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cust_discount_amount] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cust_tds_amount') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cust_tds_amount] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cust_markup') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cust_markup] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cust_addl_markup') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cust_addl_markup] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cust_ssr_markup') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cust_ssr_markup] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cust_service_fee') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cust_service_fee] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cust_addl_service_fee') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cust_addl_service_fee] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cust_ssr_service_fee') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cust_ssr_service_fee] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cust_service_fee_gst') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cust_service_fee_gst] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cust_ssr_service_fee_gst') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cust_ssr_service_fee_gst] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cust_addl_service_fee_gst') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cust_addl_service_fee_gst] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supp_commission_amount') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supp_commission_amount] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supp_tds_amount') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supp_tds_amount] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supp_markup') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supp_markup] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supp_addl_markup') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supp_addl_markup] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supp_ssr_markup') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supp_ssr_markup] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supp_service_fee') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supp_service_fee] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supp_addl_service_fee') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supp_addl_service_fee] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supp_ssr_service_fee') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supp_ssr_service_fee] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supp_service_fee_gst') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supp_service_fee_gst] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supp_ssr_service_fee_gst') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supp_ssr_service_fee_gst] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supp_addl_service_fee_gst') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supp_addl_service_fee_gst] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supplier_penalty') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supplier_penalty] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'agent_penalty') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [agent_penalty] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'penalty_amount') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [penalty_amount] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cust_markup_reversal') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cust_markup_reversal] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cust_addl_markup_reversal') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cust_addl_markup_reversal] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'cust_ssr_markup_reversal') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [cust_ssr_markup_reversal] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supp_markup_reversal') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supp_markup_reversal] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supp_addl_markup_reversal') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supp_addl_markup_reversal] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'supp_ssr_markup_reversal') IS NULL ALTER TABLE dbo.[Agent_ticket_data] ADD [supp_ssr_markup_reversal] DECIMAL(18,2) NULL;
IF COL_LENGTH('dbo.[Agent_ticket_data]', 'original_ticket_no') IS NOT NULL ALTER TABLE dbo.[Agent_ticket_data] DROP COLUMN [original_ticket_no];
GO
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = 'ix_Agent_ticket_data_invoice')
    CREATE INDEX ix_Agent_ticket_data_invoice ON dbo.[Agent_ticket_data] (company_id, booking_status, booking_reference);
GO
