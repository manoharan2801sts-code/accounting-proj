-- ==========================================================================
-- dbo.AL_TicketLines.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[AL_TicketLines]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[AL_TicketLines](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[ticket_id] [int] NOT NULL,
	[airline_code] [nvarchar](200) NULL,
	[airline_name] [nvarchar](200) NULL,
	[flight_no] [nvarchar](200) NULL,
	[ticket_no] [nvarchar](30) NOT NULL,
	[passenger_name] [nvarchar](50) NOT NULL,
	[pax_type] [nvarchar](10) NOT NULL,
	[sector] [nvarchar](200) NULL,
	[travel_date] [nvarchar](200) NULL,
	[basic_fare] [decimal](14, 2) NOT NULL,
	[yq] [decimal](14, 2) NOT NULL,
	[yr] [decimal](14, 2) NOT NULL,
	[k3_tax] [decimal](14, 2) NOT NULL,
	[tax_others] [decimal](14, 2) NOT NULL,
	[seat] [decimal](14, 2) NOT NULL,
	[meal] [decimal](14, 2) NOT NULL,
	[baggage] [decimal](14, 2) NOT NULL,
	[other_ssr] [decimal](14, 2) NOT NULL,
	[disc_on] [nvarchar](20) NULL,
	[disc_type] [nvarchar](12) NULL,
	[disc_value] [decimal](14, 2) NOT NULL,
	[tds_per] [decimal](5, 2) NOT NULL,
	[markup] [decimal](14, 2) NOT NULL,
	[addl_markup] [decimal](14, 2) NOT NULL,
	[service_fee] [decimal](14, 2) NOT NULL,
	[addl_service_fee] [decimal](14, 2) NOT NULL,
	[gst_pct] [decimal](5, 2) NOT NULL,
	[total_billed] [decimal](14, 2) NOT NULL,
	[status] [nvarchar](15) NOT NULL,
	[created_at] [datetime2](7) NOT NULL,
	[updated_at] [datetime2](7) NOT NULL,
	[airline_category] [nvarchar](5) NULL,
	[supplier_ledger_id] [int] NULL,
	[office_id] [nvarchar](30) NULL,
	[fop] [nvarchar](20) NULL,
	[supp_comm_on] [varchar](20) NULL,
	[supp_comm_type] [varchar](12) NULL,
	[supp_comm_value] [decimal](14, 2) NOT NULL,
	[supp_tds_per] [decimal](5, 2) NOT NULL,
	[cabin] [nvarchar](200) NULL,
	[travel_class] [nvarchar](200) NULL,
	[fare_type] [nvarchar](300) NULL,
	[ssr_markup] [decimal](14, 2) NOT NULL,
	[ssr_service_fee] [decimal](14, 2) NOT NULL,
	[card_number] [nvarchar](40) NULL,
	[supp_markup] [decimal](14, 2) NOT NULL,
	[supp_addl_markup] [decimal](14, 2) NOT NULL,
	[supp_service_fee] [decimal](14, 2) NOT NULL,
	[supp_addl_service_fee] [decimal](14, 2) NOT NULL,
	[supp_gst_pct] [decimal](5, 2) NOT NULL,
	[pg_charges] [numeric](14, 2) NOT NULL,
	[pg_charges_percentage] [numeric](5, 2) NULL,
	[rescheduled] [bit] NOT NULL,
	[canceled] [bit] NOT NULL,
	[supp_ssr_markup] [numeric](14, 2) NOT NULL,
	[supp_ssr_service_fee] [numeric](14, 2) NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
UNIQUE NONCLUSTERED 
(
	[ticket_no] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ('Adult') FOR [pax_type]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [basic_fare]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [yq]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [yr]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [k3_tax]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [tax_others]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [seat]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [meal]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [baggage]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [other_ssr]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [disc_value]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [tds_per]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [markup]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [addl_markup]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [service_fee]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [addl_service_fee]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [gst_pct]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [total_billed]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ('ISSUED') FOR [status]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  CONSTRAINT [DF_TicketLines_supp_disc_value]  DEFAULT ((0)) FOR [supp_comm_value]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  CONSTRAINT [DF_TicketLines_supp_tds_per]  DEFAULT ((0)) FOR [supp_tds_per]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [ssr_markup]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [ssr_service_fee]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [supp_markup]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [supp_addl_markup]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [supp_service_fee]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [supp_addl_service_fee]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [supp_gst_pct]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [rescheduled]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [canceled]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [supp_ssr_markup]
GO
ALTER TABLE [dbo].[AL_TicketLines] ADD  DEFAULT ((0)) FOR [supp_ssr_service_fee]
GO
ALTER TABLE [dbo].[AL_TicketLines]  WITH CHECK ADD  CONSTRAINT [fk_ticketlines_supplier] FOREIGN KEY([supplier_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[AL_TicketLines] CHECK CONSTRAINT [fk_ticketlines_supplier]
GO
ALTER TABLE [dbo].[AL_TicketLines]  WITH CHECK ADD  CONSTRAINT [fk_ticketlines_ticket] FOREIGN KEY([ticket_id])
REFERENCES [dbo].[AL_Tickets] ([id])
ON DELETE CASCADE
GO
ALTER TABLE [dbo].[AL_TicketLines] CHECK CONSTRAINT [fk_ticketlines_ticket]
GO


GO

-- ==========================================================================
-- dbo.AL_Tickets.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[AL_Tickets]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[AL_Tickets](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[branch_name] [nvarchar](100) NULL,
	[invoice_number] [nvarchar](20) NOT NULL,
	[invoice_date] [date] NOT NULL,
	[invoice_type] [nvarchar](100) NULL,
	[booking_mode] [nvarchar](20) NOT NULL,
	[booking_type] [nvarchar](30) NULL,
	[booking_status] [nvarchar](20) NULL,
	[customer_ledger_id] [int] NOT NULL,
	[supplier_ledger_id] [int] NULL,
	[travel_type] [nvarchar](20) NULL,
	[user_name] [nvarchar](100) NULL,
	[currency] [nvarchar](5) NOT NULL,
	[roe] [decimal](10, 4) NOT NULL,
	[booking_given_by] [nvarchar](25) NULL,
	[booking_reference] [nvarchar](30) NOT NULL,
	[booking_ref_date] [date] NULL,
	[airline_pnr] [nvarchar](13) NULL,
	[gds_pnr] [nvarchar](13) NULL,
	[office_id] [nvarchar](30) NULL,
	[payment_mode] [nvarchar](20) NULL,
	[airline_category] [nvarchar](5) NULL,
	[created_at] [datetime2](7) NOT NULL,
	[updated_at] [datetime2](7) NOT NULL,
	[payment_gateway_ref] [nvarchar](60) NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_tickets_company_booking_ref] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[booking_reference] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_tickets_company_invoice_no] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[invoice_number] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[AL_Tickets] ADD  DEFAULT ('Manual') FOR [booking_mode]
GO
ALTER TABLE [dbo].[AL_Tickets] ADD  DEFAULT ('INR') FOR [currency]
GO
ALTER TABLE [dbo].[AL_Tickets] ADD  DEFAULT ((1)) FOR [roe]
GO
ALTER TABLE [dbo].[AL_Tickets] ADD  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [dbo].[AL_Tickets] ADD  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [dbo].[AL_Tickets]  WITH CHECK ADD  CONSTRAINT [fk_tickets_customer] FOREIGN KEY([customer_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[AL_Tickets] CHECK CONSTRAINT [fk_tickets_customer]
GO
ALTER TABLE [dbo].[AL_Tickets]  WITH CHECK ADD  CONSTRAINT [fk_tickets_supplier] FOREIGN KEY([supplier_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[AL_Tickets] CHECK CONSTRAINT [fk_tickets_supplier]
GO


GO

-- ==========================================================================
-- dbo.AppUsers.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[AppUsers]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[AppUsers](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[full_name] [nvarchar](150) NOT NULL,
	[email] [nvarchar](200) NOT NULL,
	[role] [nvarchar](50) NOT NULL,
	[branch_name] [nvarchar](100) NULL,
	[is_super_admin] [bit] NOT NULL,
	[is_active] [bit] NOT NULL,
	[created_at] [datetimeoffset](7) NOT NULL,
	[updated_at] [datetimeoffset](7) NOT NULL,
	[password_hash] [nvarchar](256) NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_app_user_email] UNIQUE NONCLUSTERED 
(
	[email] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO


GO

-- ==========================================================================
-- dbo.Cancellation_AL_Tickets.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[Cancellation_AL_Tickets]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[Cancellation_AL_Tickets](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[branch_name] [nvarchar](100) NULL,
	[invoice_number] [nvarchar](20) NOT NULL,
	[invoice_date] [date] NOT NULL,
	[invoice_type] [nvarchar](100) NULL,
	[booking_mode] [nvarchar](20) NOT NULL,
	[booking_type] [nvarchar](30) NULL,
	[booking_status] [nvarchar](20) NULL,
	[travel_type] [nvarchar](20) NULL,
	[user_name] [nvarchar](100) NULL,
	[currency] [nvarchar](5) NOT NULL,
	[roe] [numeric](10, 4) NOT NULL,
	[booking_given_by] [nvarchar](25) NULL,
	[cancellation_reference] [nvarchar](30) NOT NULL,
	[cancellation_ref_date] [date] NULL,
	[airline_pnr] [nvarchar](13) NULL,
	[gds_pnr] [nvarchar](13) NULL,
	[office_id] [nvarchar](30) NULL,
	[payment_mode] [nvarchar](20) NULL,
	[payment_gateway_ref] [nvarchar](60) NULL,
	[airline_category] [nvarchar](5) NULL,
	[created_at] [datetimeoffset](7) NOT NULL,
	[updated_at] [datetimeoffset](7) NOT NULL,
	[customer_ledger_id] [int] NOT NULL,
	[original_ticket_id] [int] NOT NULL,
	[supplier_ledger_id] [int] NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_cancel_ticket_company_cancel_ref] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[cancellation_reference] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_cancel_ticket_company_invoice_no] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[invoice_number] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[Cancellation_AL_Tickets]  WITH CHECK ADD  CONSTRAINT [Cancellation_AL_Tickets_customer_ledger_id_bf3cca0c_fk_Ledgers_id] FOREIGN KEY([customer_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[Cancellation_AL_Tickets] CHECK CONSTRAINT [Cancellation_AL_Tickets_customer_ledger_id_bf3cca0c_fk_Ledgers_id]
GO
ALTER TABLE [dbo].[Cancellation_AL_Tickets]  WITH CHECK ADD  CONSTRAINT [Cancellation_AL_Tickets_original_ticket_id_b83c7442_fk_AL_Tickets_id] FOREIGN KEY([original_ticket_id])
REFERENCES [dbo].[AL_Tickets] ([id])
GO
ALTER TABLE [dbo].[Cancellation_AL_Tickets] CHECK CONSTRAINT [Cancellation_AL_Tickets_original_ticket_id_b83c7442_fk_AL_Tickets_id]
GO
ALTER TABLE [dbo].[Cancellation_AL_Tickets]  WITH CHECK ADD  CONSTRAINT [Cancellation_AL_Tickets_supplier_ledger_id_4c5e58c7_fk_Ledgers_id] FOREIGN KEY([supplier_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[Cancellation_AL_Tickets] CHECK CONSTRAINT [Cancellation_AL_Tickets_supplier_ledger_id_4c5e58c7_fk_Ledgers_id]
GO


GO

-- ==========================================================================
-- dbo.Cancellation_Al_TicketLines.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[Cancellation_Al_TicketLines]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[Cancellation_Al_TicketLines](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[airline_code] [nvarchar](200) NULL,
	[airline_name] [nvarchar](200) NULL,
	[airline_category] [nvarchar](5) NULL,
	[flight_no] [nvarchar](200) NULL,
	[ticket_no] [nvarchar](30) NOT NULL,
	[passenger_name] [nvarchar](50) NOT NULL,
	[pax_type] [nvarchar](10) NOT NULL,
	[sector] [nvarchar](200) NULL,
	[travel_date] [nvarchar](200) NULL,
	[cabin] [nvarchar](200) NULL,
	[travel_class] [nvarchar](200) NULL,
	[fare_type] [nvarchar](300) NULL,
	[basic_fare] [numeric](14, 2) NOT NULL,
	[yq] [numeric](14, 2) NOT NULL,
	[yr] [numeric](14, 2) NOT NULL,
	[k3_tax] [numeric](14, 2) NOT NULL,
	[tax_others] [numeric](14, 2) NOT NULL,
	[seat] [numeric](14, 2) NOT NULL,
	[meal] [numeric](14, 2) NOT NULL,
	[baggage] [numeric](14, 2) NOT NULL,
	[other_ssr] [numeric](14, 2) NOT NULL,
	[disc_on] [nvarchar](20) NULL,
	[disc_type] [nvarchar](12) NULL,
	[disc_value] [numeric](14, 2) NOT NULL,
	[tds_per] [numeric](5, 2) NOT NULL,
	[pg_charges] [numeric](14, 2) NOT NULL,
	[pg_charges_percentage] [numeric](5, 2) NULL,
	[markup] [numeric](14, 2) NOT NULL,
	[addl_markup] [numeric](14, 2) NOT NULL,
	[ssr_markup] [numeric](14, 2) NOT NULL,
	[service_fee] [numeric](14, 2) NOT NULL,
	[addl_service_fee] [numeric](14, 2) NOT NULL,
	[ssr_service_fee] [numeric](14, 2) NOT NULL,
	[gst_pct] [numeric](5, 2) NOT NULL,
	[supp_comm_on] [nvarchar](20) NULL,
	[supp_comm_type] [nvarchar](12) NULL,
	[supp_comm_value] [numeric](14, 2) NOT NULL,
	[supp_tds_per] [numeric](5, 2) NOT NULL,
	[supp_markup] [numeric](14, 2) NOT NULL,
	[supp_addl_markup] [numeric](14, 2) NOT NULL,
	[supp_service_fee] [numeric](14, 2) NOT NULL,
	[supp_addl_service_fee] [numeric](14, 2) NOT NULL,
	[supp_gst_pct] [numeric](5, 2) NOT NULL,
	[total_billed] [numeric](14, 2) NOT NULL,
	[status] [nvarchar](15) NOT NULL,
	[office_id] [nvarchar](30) NULL,
	[fop] [nvarchar](20) NULL,
	[card_number] [nvarchar](40) NULL,
	[created_at] [datetimeoffset](7) NOT NULL,
	[updated_at] [datetimeoffset](7) NOT NULL,
	[cancellation_ticket_id] [int] NOT NULL,
	[original_ticket_line_id] [int] NOT NULL,
	[supplier_ledger_id] [int] NULL,
	[supplier_penalty] [numeric](14, 2) NOT NULL,
	[cancellation_penalty] [numeric](14, 2) NOT NULL,
	[agent_penalty] [numeric](14, 2) NOT NULL,
	[cust_markup_reversal] [numeric](14, 2) NOT NULL,
	[cust_addl_markup_reversal] [numeric](14, 2) NOT NULL,
	[cust_ssr_markup_reversal] [numeric](14, 2) NOT NULL,
	[supp_markup_reversal] [numeric](14, 2) NOT NULL,
	[supp_addl_markup_reversal] [numeric](14, 2) NOT NULL,
	[tds_amount_override] [numeric](14, 2) NULL,
	[supp_tds_amount_override] [numeric](14, 2) NULL,
	[supp_ssr_markup_reversal] [numeric](14, 2) NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
UNIQUE NONCLUSTERED 
(
	[original_ticket_line_id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_cancel_ticketline_ticket_no] UNIQUE NONCLUSTERED 
(
	[ticket_no] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines] ADD  DEFAULT ((0)) FOR [supplier_penalty]
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines] ADD  DEFAULT ((0)) FOR [cancellation_penalty]
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines] ADD  DEFAULT ((0)) FOR [agent_penalty]
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines] ADD  DEFAULT ((0)) FOR [cust_markup_reversal]
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines] ADD  DEFAULT ((0)) FOR [cust_addl_markup_reversal]
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines] ADD  DEFAULT ((0)) FOR [cust_ssr_markup_reversal]
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines] ADD  DEFAULT ((0)) FOR [supp_markup_reversal]
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines] ADD  DEFAULT ((0)) FOR [supp_addl_markup_reversal]
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines] ADD  DEFAULT ((0)) FOR [supp_ssr_markup_reversal]
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines]  WITH CHECK ADD  CONSTRAINT [Cancellation_Al_TicketLines_cancellation_ticket_id_384c3097_fk_Cancellation_AL_Tickets_id] FOREIGN KEY([cancellation_ticket_id])
REFERENCES [dbo].[Cancellation_AL_Tickets] ([id])
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines] CHECK CONSTRAINT [Cancellation_Al_TicketLines_cancellation_ticket_id_384c3097_fk_Cancellation_AL_Tickets_id]
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines]  WITH CHECK ADD  CONSTRAINT [Cancellation_Al_TicketLines_original_ticket_line_id_64211902_fk_AL_TicketLines_id] FOREIGN KEY([original_ticket_line_id])
REFERENCES [dbo].[AL_TicketLines] ([id])
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines] CHECK CONSTRAINT [Cancellation_Al_TicketLines_original_ticket_line_id_64211902_fk_AL_TicketLines_id]
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines]  WITH CHECK ADD  CONSTRAINT [Cancellation_Al_TicketLines_supplier_ledger_id_682d726b_fk_Ledgers_id] FOREIGN KEY([supplier_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[Cancellation_Al_TicketLines] CHECK CONSTRAINT [Cancellation_Al_TicketLines_supplier_ledger_id_682d726b_fk_Ledgers_id]
GO


GO

-- ==========================================================================
-- dbo.CompanyMaster.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[CompanyMaster]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[CompanyMaster](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_name] [nvarchar](200) NOT NULL,
	[mailing_name] [nvarchar](200) NULL,
	[address] [nvarchar](max) NULL,
	[country] [nvarchar](100) NOT NULL,
	[state] [nvarchar](100) NULL,
	[pincode] [nvarchar](6) NULL,
	[telephone] [nvarchar](20) NULL,
	[mobile] [nvarchar](10) NULL,
	[email] [nvarchar](200) NULL,
	[financial_year_from] [date] NULL,
	[books_beginning_from] [date] NULL,
	[gst_reg_type] [nvarchar](20) NOT NULL,
	[gst_no] [nvarchar](15) NULL,
	[cin_number] [nvarchar](25) NULL,
	[tan_number] [nvarchar](15) NULL,
	[hsn_sac] [nvarchar](20) NULL,
	[created_at] [datetime2](7) NOT NULL,
	[updated_at] [datetime2](7) NOT NULL,
	[pan_number] [nvarchar](10) NULL,
	[currency_name] [nvarchar](50) NULL,
	[currency_symbol] [nvarchar](5) NULL,
	[decimal_places] [smallint] NULL,
	[logo_base64] [nvarchar](max) NULL,
	[seal_base64] [nvarchar](max) NULL,
	[invoice_template] [nvarchar](20) NOT NULL,
	[terms_conditions] [nvarchar](max) NULL,
	[bank_account_holder] [nvarchar](100) NULL,
	[bank_account_no] [nvarchar](30) NULL,
	[bank_ifsc] [nvarchar](15) NULL,
	[bank_swift] [nvarchar](15) NULL,
	[bank_name] [nvarchar](100) NULL,
	[bank_branch] [nvarchar](100) NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_company_master_name] UNIQUE NONCLUSTERED 
(
	[company_name] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO
ALTER TABLE [dbo].[CompanyMaster] ADD  DEFAULT ('India') FOR [country]
GO
ALTER TABLE [dbo].[CompanyMaster] ADD  DEFAULT ('Regular') FOR [gst_reg_type]
GO
ALTER TABLE [dbo].[CompanyMaster] ADD  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [dbo].[CompanyMaster] ADD  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [dbo].[CompanyMaster] ADD  DEFAULT ('classic') FOR [invoice_template]
GO
ALTER TABLE [dbo].[CompanyMaster]  WITH CHECK ADD CHECK  (([decimal_places]>=(0)))
GO
ALTER TABLE [dbo].[CompanyMaster]  WITH CHECK ADD CHECK  (([gst_reg_type]='SEZ' OR [gst_reg_type]='Unregistered' OR [gst_reg_type]='Composition' OR [gst_reg_type]='Regular'))
GO


GO

-- ==========================================================================
-- dbo.FOPMaster.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[FOPMaster]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[FOPMaster](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[card_type] [nvarchar](20) NOT NULL,
	[card_number] [nvarchar](40) NOT NULL,
	[card_master_ledger_id] [int] NULL,
	[card_master_ledger_name] [nvarchar](200) NULL,
	[is_active] [bit] NOT NULL,
	[created_at] [datetime2](7) NOT NULL,
	[updated_at] [datetime2](7) NOT NULL,
	[bank_name] [nvarchar](100) NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_fop_master_card_number] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[card_number] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[FOPMaster] ADD  DEFAULT ((1)) FOR [is_active]
GO
ALTER TABLE [dbo].[FOPMaster] ADD  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [dbo].[FOPMaster] ADD  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [dbo].[FOPMaster]  WITH CHECK ADD  CONSTRAINT [FOPMaster_card_master_ledger_id_680d0290_fk_Ledgers_id] FOREIGN KEY([card_master_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[FOPMaster] CHECK CONSTRAINT [FOPMaster_card_master_ledger_id_680d0290_fk_Ledgers_id]
GO
ALTER TABLE [dbo].[FOPMaster]  WITH CHECK ADD  CONSTRAINT [ck_fop_master_card_type] CHECK  (([card_type]='Client Card' OR [card_type]='Own Card'))
GO
ALTER TABLE [dbo].[FOPMaster] CHECK CONSTRAINT [ck_fop_master_card_type]
GO


GO

-- ==========================================================================
-- dbo.JournalVoucher.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[JournalVoucher]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[JournalVoucher](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[branch_name] [nvarchar](100) NULL,
	[voucher_type] [nvarchar](20) NOT NULL,
	[voucher_date] [date] NOT NULL,
	[narration] [nvarchar](250) NULL,
	[source_ticket_id] [int] NULL,
	[total_debit] [decimal](16, 2) NOT NULL,
	[total_credit] [decimal](16, 2) NOT NULL,
	[created_at] [datetime2](7) NOT NULL,
	[updated_at] [datetime2](7) NOT NULL,
	[category] [nvarchar](20) NOT NULL,
	[voucher_no] [nvarchar](20) NULL,
	[lines_json] [nvarchar](max) NULL,
	[source_reschedule_ticket_id] [int] NULL,
	[source_cancellation_ticket_id] [int] NULL,
	[source_ssr_ticket_id] [int] NULL,
 CONSTRAINT [PK_JournalVoucher] PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_journal_voucher_company_no] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[voucher_no] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO
ALTER TABLE [dbo].[JournalVoucher] ADD  CONSTRAINT [DF_JournalVoucher_voucher_type]  DEFAULT ('Tax Invoice') FOR [voucher_type]
GO
ALTER TABLE [dbo].[JournalVoucher] ADD  CONSTRAINT [DF_JournalVoucher_total_debit]  DEFAULT ((0)) FOR [total_debit]
GO
ALTER TABLE [dbo].[JournalVoucher] ADD  CONSTRAINT [DF_JournalVoucher_total_credit]  DEFAULT ((0)) FOR [total_credit]
GO
ALTER TABLE [dbo].[JournalVoucher] ADD  CONSTRAINT [DF_JournalVoucher_created_at]  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [dbo].[JournalVoucher] ADD  CONSTRAINT [DF_JournalVoucher_updated_at]  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [dbo].[JournalVoucher] ADD  CONSTRAINT [DF_JournalVoucher_category]  DEFAULT ('AIRLINE') FOR [category]
GO
ALTER TABLE [dbo].[JournalVoucher]  WITH CHECK ADD  CONSTRAINT [fk_vouchers_ticket] FOREIGN KEY([source_ticket_id])
REFERENCES [dbo].[AL_Tickets] ([id])
ON DELETE SET NULL
GO
ALTER TABLE [dbo].[JournalVoucher] CHECK CONSTRAINT [fk_vouchers_ticket]
GO
ALTER TABLE [dbo].[JournalVoucher]  WITH CHECK ADD  CONSTRAINT [JournalVoucher_source_cancellation_ticket_id_c40f008d_fk_Cancellation_AL_Tickets_id] FOREIGN KEY([source_cancellation_ticket_id])
REFERENCES [dbo].[Cancellation_AL_Tickets] ([id])
GO
ALTER TABLE [dbo].[JournalVoucher] CHECK CONSTRAINT [JournalVoucher_source_cancellation_ticket_id_c40f008d_fk_Cancellation_AL_Tickets_id]
GO
ALTER TABLE [dbo].[JournalVoucher]  WITH CHECK ADD  CONSTRAINT [JournalVoucher_source_reschedule_ticket_id_8b753ac0_fk_RescheduleAirlineTickets_id] FOREIGN KEY([source_reschedule_ticket_id])
REFERENCES [dbo].[Rescheduled_Al_Ticket] ([id])
GO
ALTER TABLE [dbo].[JournalVoucher] CHECK CONSTRAINT [JournalVoucher_source_reschedule_ticket_id_8b753ac0_fk_RescheduleAirlineTickets_id]
GO
ALTER TABLE [dbo].[JournalVoucher]  WITH CHECK ADD  CONSTRAINT [JournalVoucher_source_ssr_ticket_id_000bcaed_fk_SSR_AL_Tickets_id] FOREIGN KEY([source_ssr_ticket_id])
REFERENCES [dbo].[SSR_AL_Tickets] ([id])
GO
ALTER TABLE [dbo].[JournalVoucher] CHECK CONSTRAINT [JournalVoucher_source_ssr_ticket_id_000bcaed_fk_SSR_AL_Tickets_id]
GO


GO

-- ==========================================================================
-- dbo.Ledger_Groups.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[Ledger_Groups]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[Ledger_Groups](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[name] [nvarchar](100) NOT NULL,
	[code] [nvarchar](20) NULL,
	[account_type] [nvarchar](20) NOT NULL,
	[parent_id] [int] NULL,
	[is_group] [bit] NOT NULL,
	[is_system] [bit] NOT NULL,
	[created_at] [datetime2](7) NOT NULL,
	[updated_at] [datetime2](7) NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_ledger_groups_company_parent_name] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[parent_id] ASC,
	[name] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[Ledger_Groups] ADD  DEFAULT ((1)) FOR [is_group]
GO
ALTER TABLE [dbo].[Ledger_Groups] ADD  DEFAULT ((0)) FOR [is_system]
GO
ALTER TABLE [dbo].[Ledger_Groups] ADD  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [dbo].[Ledger_Groups] ADD  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [dbo].[Ledger_Groups]  WITH CHECK ADD  CONSTRAINT [fk_ledger_groups_parent] FOREIGN KEY([parent_id])
REFERENCES [dbo].[Ledger_Groups] ([id])
GO
ALTER TABLE [dbo].[Ledger_Groups] CHECK CONSTRAINT [fk_ledger_groups_parent]
GO
ALTER TABLE [dbo].[Ledger_Groups]  WITH CHECK ADD  CONSTRAINT [ck_ledger_groups_account_type] CHECK  (([account_type]='EQUITY' OR [account_type]='EXPENSE' OR [account_type]='INCOME' OR [account_type]='LIABILITY' OR [account_type]='ASSET'))
GO
ALTER TABLE [dbo].[Ledger_Groups] CHECK CONSTRAINT [ck_ledger_groups_account_type]
GO


GO

-- ==========================================================================
-- dbo.Ledgers.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[Ledgers]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[Ledgers](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[name] [nvarchar](150) NOT NULL,
	[group_id] [int] NOT NULL,
	[account_type] [nvarchar](20) NOT NULL,
	[ledger_category] [nvarchar](20) NOT NULL,
	[opening_balance] [decimal](18, 2) NOT NULL,
	[opening_balance_type] [nvarchar](10) NOT NULL,
	[bank_account_no] [nvarchar](40) NULL,
	[bank_branch] [nvarchar](100) NULL,
	[ifsc_code] [nvarchar](15) NULL,
	[swift_code] [nvarchar](15) NULL,
	[alias_name] [nvarchar](100) NULL,
	[address_line1] [nvarchar](150) NULL,
	[address_line2] [nvarchar](150) NULL,
	[agent_id] [nvarchar](30) NULL,
	[city] [nvarchar](60) NULL,
	[pincode] [nvarchar](10) NULL,
	[state_name] [nvarchar](60) NULL,
	[gst_no] [nvarchar](20) NULL,
	[gst_registration_type] [nvarchar](20) NULL,
	[pan_no] [nvarchar](15) NULL,
	[emirate] [nvarchar](30) NULL,
	[po_box_no] [nvarchar](20) NULL,
	[vat_trn_no] [nvarchar](20) NULL,
	[trade_license_no] [nvarchar](30) NULL,
	[trade_license_expiry] [date] NULL,
	[creditor_type] [nvarchar](30) NULL,
	[supplier_code] [nvarchar](30) NULL,
	[office_id] [nvarchar](30) NULL,
	[tax_category] [nvarchar](10) NULL,
	[tax_type] [nvarchar](10) NULL,
	[gst_applicable] [bit] NOT NULL,
	[gst_tax_type] [nvarchar](10) NULL,
	[gst_percentage] [decimal](5, 2) NOT NULL,
	[tds_applicable] [bit] NOT NULL,
	[tds_percentage] [decimal](5, 2) NOT NULL,
	[hsn_code] [nvarchar](15) NULL,
	[tcs_applicable] [bit] NOT NULL,
	[tcs_percentage] [decimal](5, 2) NOT NULL,
	[is_system] [bit] NOT NULL,
	[created_at] [datetime2](7) NOT NULL,
	[updated_at] [datetime2](7) NOT NULL,
	[maintain_balance_bill_wise] [nvarchar](5) NULL,
	[place_of_supply] [nvarchar](60) NULL,
	[is_default_bank] [bit] NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_ledgers_company_name] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[name] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[Ledgers] ADD  DEFAULT ((0)) FOR [opening_balance]
GO
ALTER TABLE [dbo].[Ledgers] ADD  DEFAULT ('Debit') FOR [opening_balance_type]
GO
ALTER TABLE [dbo].[Ledgers] ADD  DEFAULT ((0)) FOR [gst_applicable]
GO
ALTER TABLE [dbo].[Ledgers] ADD  DEFAULT ((0)) FOR [gst_percentage]
GO
ALTER TABLE [dbo].[Ledgers] ADD  DEFAULT ((0)) FOR [tds_applicable]
GO
ALTER TABLE [dbo].[Ledgers] ADD  DEFAULT ((0)) FOR [tds_percentage]
GO
ALTER TABLE [dbo].[Ledgers] ADD  DEFAULT ((0)) FOR [tcs_applicable]
GO
ALTER TABLE [dbo].[Ledgers] ADD  DEFAULT ((0)) FOR [tcs_percentage]
GO
ALTER TABLE [dbo].[Ledgers] ADD  DEFAULT ((0)) FOR [is_system]
GO
ALTER TABLE [dbo].[Ledgers] ADD  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [dbo].[Ledgers] ADD  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [dbo].[Ledgers] ADD  DEFAULT ((0)) FOR [is_default_bank]
GO
ALTER TABLE [dbo].[Ledgers]  WITH CHECK ADD  CONSTRAINT [fk_ledgers_group] FOREIGN KEY([group_id])
REFERENCES [dbo].[Ledger_Groups] ([id])
GO
ALTER TABLE [dbo].[Ledgers] CHECK CONSTRAINT [fk_ledgers_group]
GO
ALTER TABLE [dbo].[Ledgers]  WITH CHECK ADD  CONSTRAINT [ck_ledgers_balance_type] CHECK  (([opening_balance_type]='Credit' OR [opening_balance_type]='Debit'))
GO
ALTER TABLE [dbo].[Ledgers] CHECK CONSTRAINT [ck_ledgers_balance_type]
GO


GO

-- ==========================================================================
-- dbo.MasterMapping.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[MasterMapping]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[MasterMapping](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[product_type] [nvarchar](20) NOT NULL,
	[masters_category] [nvarchar](40) NOT NULL,
	[masters_category_id] [tinyint] NOT NULL,
	[field_name] [nvarchar](60) NOT NULL,
	[ledger_id] [int] NOT NULL,
	[ledger_name] [nvarchar](200) NULL,
	[effective_from] [date] NOT NULL,
	[created_at] [datetime2](7) NOT NULL,
	[updated_at] [datetime2](7) NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_master_mapping_field] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[product_type] ASC,
	[field_name] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[MasterMapping] ADD  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [dbo].[MasterMapping] ADD  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [dbo].[MasterMapping]  WITH CHECK ADD  CONSTRAINT [fk_master_mapping_ledger] FOREIGN KEY([ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[MasterMapping] CHECK CONSTRAINT [fk_master_mapping_ledger]
GO
ALTER TABLE [dbo].[MasterMapping]  WITH CHECK ADD  CONSTRAINT [ck_master_mapping_masters_category] CHECK  (([masters_category]='GST and TDS' OR [masters_category]='Expenditure To Supplier' OR [masters_category]='Expenditure To Customer' OR [masters_category]='Earnings From Supplier' OR [masters_category]='Earnings From Customer'))
GO
ALTER TABLE [dbo].[MasterMapping] CHECK CONSTRAINT [ck_master_mapping_masters_category]
GO
ALTER TABLE [dbo].[MasterMapping]  WITH CHECK ADD  CONSTRAINT [ck_master_mapping_masters_category_id] CHECK  (([masters_category_id]>=(1) AND [masters_category_id]<=(5)))
GO
ALTER TABLE [dbo].[MasterMapping] CHECK CONSTRAINT [ck_master_mapping_masters_category_id]
GO
ALTER TABLE [dbo].[MasterMapping]  WITH CHECK ADD  CONSTRAINT [ck_master_mapping_product_type] CHECK  (([product_type]='Rail' OR [product_type]='Insurance' OR [product_type]='Visa' OR [product_type]='Bus' OR [product_type]='Hotel' OR [product_type]='Airline'))
GO
ALTER TABLE [dbo].[MasterMapping] CHECK CONSTRAINT [ck_master_mapping_product_type]
GO


GO

-- ==========================================================================
-- dbo.MasterMappingHistory.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[MasterMappingHistory]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[MasterMappingHistory](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[product_type] [nvarchar](20) NOT NULL,
	[masters_category] [nvarchar](40) NOT NULL,
	[field_name] [nvarchar](60) NOT NULL,
	[ledger_id] [int] NOT NULL,
	[ledger_name] [nvarchar](200) NULL,
	[effective_from] [date] NOT NULL,
	[created_at] [datetimeoffset](7) NOT NULL,
	[updated_at] [datetimeoffset](7) NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_master_mapping_history_effective_from] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[product_type] ASC,
	[field_name] ASC,
	[effective_from] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO


GO

-- ==========================================================================
-- dbo.MenuMaster.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[MenuMaster]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[MenuMaster](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[menu_key] [nvarchar](60) NOT NULL,
	[title] [nvarchar](100) NOT NULL,
	[parent_key] [nvarchar](60) NULL,
	[module] [nvarchar](20) NOT NULL,
	[sort_order] [int] NOT NULL,
	[is_active] [bit] NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_menu_master_key] UNIQUE NONCLUSTERED 
(
	[menu_key] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[MenuMaster]  WITH CHECK ADD  CONSTRAINT [MenuMaster_sort_order_329c4067_check] CHECK  (([sort_order]>=(0)))
GO
ALTER TABLE [dbo].[MenuMaster] CHECK CONSTRAINT [MenuMaster_sort_order_329c4067_check]
GO


GO

-- ==========================================================================
-- dbo.PGMaster.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[PGMaster]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[PGMaster](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[gateway_name] [nvarchar](100) NOT NULL,
	[payment_master_ledger_id] [int] NOT NULL,
	[payment_master_ledger_name] [nvarchar](200) NULL,
	[is_active] [bit] NOT NULL,
	[created_at] [datetime2](7) NOT NULL,
	[updated_at] [datetime2](7) NOT NULL,
	[pg_charges_master_ledger_id] [int] NULL,
	[pg_charges_master_ledger_name] [nvarchar](200) NULL,
	[pg_charges_percentage] [numeric](5, 2) NULL,
	[pg_charges_percentage_effective_from] [date] NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_pg_master_gateway_name] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[gateway_name] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[PGMaster] ADD  DEFAULT ((1)) FOR [is_active]
GO
ALTER TABLE [dbo].[PGMaster] ADD  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [dbo].[PGMaster] ADD  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [dbo].[PGMaster]  WITH CHECK ADD  CONSTRAINT [fk_pg_master_ledger] FOREIGN KEY([payment_master_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[PGMaster] CHECK CONSTRAINT [fk_pg_master_ledger]
GO
ALTER TABLE [dbo].[PGMaster]  WITH CHECK ADD  CONSTRAINT [FK_PGMaster_PGChargesMasterLedger] FOREIGN KEY([pg_charges_master_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[PGMaster] CHECK CONSTRAINT [FK_PGMaster_PGChargesMasterLedger]
GO
ALTER TABLE [dbo].[PGMaster]  WITH CHECK ADD  CONSTRAINT [PGMaster_pg_charges_master_ledger_id_6c7b4b7c_fk_Ledgers_id] FOREIGN KEY([pg_charges_master_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[PGMaster] CHECK CONSTRAINT [PGMaster_pg_charges_master_ledger_id_6c7b4b7c_fk_Ledgers_id]
GO


GO

-- ==========================================================================
-- dbo.PGMasterHistory.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[PGMasterHistory]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[PGMasterHistory](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[gateway_name] [nvarchar](100) NOT NULL,
	[payment_master_ledger_id] [int] NULL,
	[payment_master_ledger_name] [nvarchar](200) NULL,
	[pg_charges_master_ledger_id] [int] NULL,
	[pg_charges_master_ledger_name] [nvarchar](200) NULL,
	[pg_charges_percentage] [numeric](5, 2) NULL,
	[effective_from] [date] NOT NULL,
	[created_at] [datetimeoffset](7) NOT NULL,
	[pg_master_id] [int] NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_pg_master_history_effective_from] UNIQUE NONCLUSTERED 
(
	[pg_master_id] ASC,
	[effective_from] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[PGMasterHistory]  WITH CHECK ADD  CONSTRAINT [PGMasterHistory_pg_master_id_cf94d780_fk_PGMaster_id] FOREIGN KEY([pg_master_id])
REFERENCES [dbo].[PGMaster] ([id])
GO
ALTER TABLE [dbo].[PGMasterHistory] CHECK CONSTRAINT [PGMasterHistory_pg_master_id_cf94d780_fk_PGMaster_id]
GO


GO

-- ==========================================================================
-- dbo.Rescheduled_Al_Ticket.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[Rescheduled_Al_Ticket]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[Rescheduled_Al_Ticket](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[branch_name] [nvarchar](100) NULL,
	[invoice_number] [nvarchar](20) NOT NULL,
	[invoice_date] [date] NOT NULL,
	[invoice_type] [nvarchar](100) NULL,
	[booking_mode] [nvarchar](20) NOT NULL,
	[booking_type] [nvarchar](30) NULL,
	[booking_status] [nvarchar](20) NULL,
	[travel_type] [nvarchar](20) NULL,
	[user_name] [nvarchar](100) NULL,
	[currency] [nvarchar](5) NOT NULL,
	[roe] [numeric](10, 4) NOT NULL,
	[booking_given_by] [nvarchar](25) NULL,
	[booking_reference] [nvarchar](30) NOT NULL,
	[booking_ref_date] [date] NULL,
	[airline_pnr] [nvarchar](13) NULL,
	[gds_pnr] [nvarchar](13) NULL,
	[office_id] [nvarchar](30) NULL,
	[payment_mode] [nvarchar](20) NULL,
	[payment_gateway_ref] [nvarchar](60) NULL,
	[airline_category] [nvarchar](5) NULL,
	[created_at] [datetimeoffset](7) NOT NULL,
	[updated_at] [datetimeoffset](7) NOT NULL,
	[customer_ledger_id] [int] NOT NULL,
	[original_ticket_id] [int] NOT NULL,
	[supplier_ledger_id] [int] NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_resched_ticket_company_booking_ref] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[booking_reference] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_resched_ticket_company_invoice_no] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[invoice_number] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[Rescheduled_Al_Ticket]  WITH CHECK ADD  CONSTRAINT [RescheduleAirlineTickets_customer_ledger_id_97fcdf54_fk_Ledgers_id] FOREIGN KEY([customer_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[Rescheduled_Al_Ticket] CHECK CONSTRAINT [RescheduleAirlineTickets_customer_ledger_id_97fcdf54_fk_Ledgers_id]
GO
ALTER TABLE [dbo].[Rescheduled_Al_Ticket]  WITH CHECK ADD  CONSTRAINT [RescheduleAirlineTickets_original_ticket_id_3017ea57_fk_Tickets_id] FOREIGN KEY([original_ticket_id])
REFERENCES [dbo].[AL_Tickets] ([id])
GO
ALTER TABLE [dbo].[Rescheduled_Al_Ticket] CHECK CONSTRAINT [RescheduleAirlineTickets_original_ticket_id_3017ea57_fk_Tickets_id]
GO
ALTER TABLE [dbo].[Rescheduled_Al_Ticket]  WITH CHECK ADD  CONSTRAINT [RescheduleAirlineTickets_supplier_ledger_id_ab4599ef_fk_Ledgers_id] FOREIGN KEY([supplier_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[Rescheduled_Al_Ticket] CHECK CONSTRAINT [RescheduleAirlineTickets_supplier_ledger_id_ab4599ef_fk_Ledgers_id]
GO


GO

-- ==========================================================================
-- dbo.Rescheduled_Al_TicketLines.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[Rescheduled_Al_TicketLines]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[Rescheduled_Al_TicketLines](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[airline_code] [nvarchar](200) NULL,
	[airline_name] [nvarchar](200) NULL,
	[airline_category] [nvarchar](5) NULL,
	[flight_no] [nvarchar](200) NULL,
	[ticket_no] [nvarchar](30) NOT NULL,
	[passenger_name] [nvarchar](50) NOT NULL,
	[pax_type] [nvarchar](10) NOT NULL,
	[sector] [nvarchar](200) NULL,
	[travel_date] [nvarchar](200) NULL,
	[cabin] [nvarchar](200) NULL,
	[travel_class] [nvarchar](200) NULL,
	[fare_type] [nvarchar](300) NULL,
	[basic_fare] [numeric](14, 2) NOT NULL,
	[yq] [numeric](14, 2) NOT NULL,
	[yr] [numeric](14, 2) NOT NULL,
	[k3_tax] [numeric](14, 2) NOT NULL,
	[tax_others] [numeric](14, 2) NOT NULL,
	[seat] [numeric](14, 2) NOT NULL,
	[meal] [numeric](14, 2) NOT NULL,
	[baggage] [numeric](14, 2) NOT NULL,
	[other_ssr] [numeric](14, 2) NOT NULL,
	[disc_on] [nvarchar](20) NULL,
	[disc_type] [nvarchar](12) NULL,
	[disc_value] [numeric](14, 2) NOT NULL,
	[tds_per] [numeric](5, 2) NOT NULL,
	[pg_charges] [numeric](14, 2) NOT NULL,
	[pg_charges_percentage] [numeric](5, 2) NULL,
	[markup] [numeric](14, 2) NOT NULL,
	[addl_markup] [numeric](14, 2) NOT NULL,
	[ssr_markup] [numeric](14, 2) NOT NULL,
	[service_fee] [numeric](14, 2) NOT NULL,
	[addl_service_fee] [numeric](14, 2) NOT NULL,
	[ssr_service_fee] [numeric](14, 2) NOT NULL,
	[gst_pct] [numeric](5, 2) NOT NULL,
	[supp_comm_on] [nvarchar](20) NULL,
	[supp_comm_type] [nvarchar](12) NULL,
	[supp_comm_value] [numeric](14, 2) NOT NULL,
	[supp_tds_per] [numeric](5, 2) NOT NULL,
	[supp_markup] [numeric](14, 2) NOT NULL,
	[supp_addl_markup] [numeric](14, 2) NOT NULL,
	[supp_service_fee] [numeric](14, 2) NOT NULL,
	[supp_addl_service_fee] [numeric](14, 2) NOT NULL,
	[supp_gst_pct] [numeric](5, 2) NOT NULL,
	[agent_penalty] [numeric](14, 2) NOT NULL,
	[reschedule_penalty] [numeric](14, 2) NOT NULL,
	[total_billed] [numeric](14, 2) NOT NULL,
	[status] [nvarchar](15) NOT NULL,
	[office_id] [nvarchar](30) NULL,
	[fop] [nvarchar](20) NULL,
	[card_number] [nvarchar](40) NULL,
	[created_at] [datetimeoffset](7) NOT NULL,
	[updated_at] [datetimeoffset](7) NOT NULL,
	[original_ticket_line_id] [int] NOT NULL,
	[reschedule_ticket_id] [int] NOT NULL,
	[supplier_ledger_id] [int] NULL,
	[supplier_penalty] [numeric](14, 2) NOT NULL,
	[based_on_reschedule_line_id] [int] NULL,
	[rescheduled] [bit] NOT NULL,
	[parent_pnr] [nvarchar](30) NULL,
	[canceled] [bit] NOT NULL,
	[supp_ssr_markup] [numeric](14, 2) NOT NULL,
	[supp_ssr_service_fee] [numeric](14, 2) NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_resched_ticketline_ticket_no] UNIQUE NONCLUSTERED 
(
	[ticket_no] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[Rescheduled_Al_TicketLines] ADD  DEFAULT ((0)) FOR [rescheduled]
GO
ALTER TABLE [dbo].[Rescheduled_Al_TicketLines] ADD  DEFAULT ((0)) FOR [canceled]
GO
ALTER TABLE [dbo].[Rescheduled_Al_TicketLines] ADD  DEFAULT ((0)) FOR [supp_ssr_markup]
GO
ALTER TABLE [dbo].[Rescheduled_Al_TicketLines] ADD  DEFAULT ((0)) FOR [supp_ssr_service_fee]
GO
ALTER TABLE [dbo].[Rescheduled_Al_TicketLines]  WITH CHECK ADD  CONSTRAINT [RescheduleAirlineTicketLines_based_on_reschedule_line_id_e8efe3e1_fk_RescheduleAirlineTicketLines_id] FOREIGN KEY([based_on_reschedule_line_id])
REFERENCES [dbo].[Rescheduled_Al_TicketLines] ([id])
GO
ALTER TABLE [dbo].[Rescheduled_Al_TicketLines] CHECK CONSTRAINT [RescheduleAirlineTicketLines_based_on_reschedule_line_id_e8efe3e1_fk_RescheduleAirlineTicketLines_id]
GO
ALTER TABLE [dbo].[Rescheduled_Al_TicketLines]  WITH CHECK ADD  CONSTRAINT [RescheduleAirlineTicketLines_original_ticket_line_id_4e539def_fk_TicketLines_id] FOREIGN KEY([original_ticket_line_id])
REFERENCES [dbo].[AL_TicketLines] ([id])
GO
ALTER TABLE [dbo].[Rescheduled_Al_TicketLines] CHECK CONSTRAINT [RescheduleAirlineTicketLines_original_ticket_line_id_4e539def_fk_TicketLines_id]
GO
ALTER TABLE [dbo].[Rescheduled_Al_TicketLines]  WITH CHECK ADD  CONSTRAINT [RescheduleAirlineTicketLines_reschedule_ticket_id_80171f6b_fk_RescheduleAirlineTickets_id] FOREIGN KEY([reschedule_ticket_id])
REFERENCES [dbo].[Rescheduled_Al_Ticket] ([id])
GO
ALTER TABLE [dbo].[Rescheduled_Al_TicketLines] CHECK CONSTRAINT [RescheduleAirlineTicketLines_reschedule_ticket_id_80171f6b_fk_RescheduleAirlineTickets_id]
GO
ALTER TABLE [dbo].[Rescheduled_Al_TicketLines]  WITH CHECK ADD  CONSTRAINT [RescheduleAirlineTicketLines_supplier_ledger_id_88a055b6_fk_Ledgers_id] FOREIGN KEY([supplier_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[Rescheduled_Al_TicketLines] CHECK CONSTRAINT [RescheduleAirlineTicketLines_supplier_ledger_id_88a055b6_fk_Ledgers_id]
GO


GO

-- ==========================================================================
-- dbo.SSR_AL_TicketLines.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[SSR_AL_TicketLines]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[SSR_AL_TicketLines](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[ticket_no] [nvarchar](20) NULL,
	[passenger_name] [nvarchar](100) NULL,
	[pax_type] [nvarchar](10) NULL,
	[airline_category] [nvarchar](5) NULL,
	[sector] [nvarchar](20) NULL,
	[office_id] [nvarchar](30) NULL,
	[fop] [nvarchar](20) NULL,
	[ssr_items] [nvarchar](max) NULL,
	[seat] [numeric](14, 2) NOT NULL,
	[meal] [numeric](14, 2) NOT NULL,
	[baggage] [numeric](14, 2) NOT NULL,
	[other_ssr] [numeric](14, 2) NOT NULL,
	[markup] [numeric](14, 2) NOT NULL,
	[service_fee] [numeric](14, 2) NOT NULL,
	[supp_markup] [numeric](14, 2) NOT NULL,
	[supp_service_fee] [numeric](14, 2) NOT NULL,
	[total_billed] [numeric](14, 2) NOT NULL,
	[original_ticket_line_id] [int] NOT NULL,
	[reschedule_line_id] [int] NULL,
	[ssr_ticket_id] [int] NOT NULL,
	[supplier_ledger_id] [int] NULL,
	[ssr_ticket_numbers] [nvarchar](max) NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines] ADD  DEFAULT ((0)) FOR [seat]
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines] ADD  DEFAULT ((0)) FOR [meal]
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines] ADD  DEFAULT ((0)) FOR [baggage]
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines] ADD  DEFAULT ((0)) FOR [other_ssr]
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines] ADD  DEFAULT ((0)) FOR [markup]
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines] ADD  DEFAULT ((0)) FOR [service_fee]
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines] ADD  DEFAULT ((0)) FOR [supp_markup]
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines] ADD  DEFAULT ((0)) FOR [supp_service_fee]
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines] ADD  DEFAULT ((0)) FOR [total_billed]
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines]  WITH CHECK ADD  CONSTRAINT [SSR_AL_TicketLines_original_ticket_line_id_c5568eb5_fk_AL_TicketLines_id] FOREIGN KEY([original_ticket_line_id])
REFERENCES [dbo].[AL_TicketLines] ([id])
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines] CHECK CONSTRAINT [SSR_AL_TicketLines_original_ticket_line_id_c5568eb5_fk_AL_TicketLines_id]
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines]  WITH CHECK ADD  CONSTRAINT [SSR_AL_TicketLines_reschedule_line_id_a84f1e8f_fk_Rescheduled_Al_TicketLines_id] FOREIGN KEY([reschedule_line_id])
REFERENCES [dbo].[Rescheduled_Al_TicketLines] ([id])
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines] CHECK CONSTRAINT [SSR_AL_TicketLines_reschedule_line_id_a84f1e8f_fk_Rescheduled_Al_TicketLines_id]
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines]  WITH CHECK ADD  CONSTRAINT [SSR_AL_TicketLines_ssr_ticket_id_1c10614f_fk_SSR_AL_Tickets_id] FOREIGN KEY([ssr_ticket_id])
REFERENCES [dbo].[SSR_AL_Tickets] ([id])
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines] CHECK CONSTRAINT [SSR_AL_TicketLines_ssr_ticket_id_1c10614f_fk_SSR_AL_Tickets_id]
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines]  WITH CHECK ADD  CONSTRAINT [SSR_AL_TicketLines_supplier_ledger_id_290c9ccd_fk_Ledgers_id] FOREIGN KEY([supplier_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[SSR_AL_TicketLines] CHECK CONSTRAINT [SSR_AL_TicketLines_supplier_ledger_id_290c9ccd_fk_Ledgers_id]
GO


GO

-- ==========================================================================
-- dbo.SSR_AL_Tickets.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[SSR_AL_Tickets]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[SSR_AL_Tickets](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[branch_name] [nvarchar](100) NULL,
	[invoice_number] [nvarchar](20) NOT NULL,
	[invoice_date] [date] NOT NULL,
	[invoice_type] [nvarchar](100) NULL,
	[booking_mode] [nvarchar](20) NOT NULL,
	[booking_status] [nvarchar](20) NOT NULL,
	[travel_type] [nvarchar](20) NULL,
	[user_name] [nvarchar](100) NULL,
	[currency] [nvarchar](5) NOT NULL,
	[roe] [numeric](10, 4) NOT NULL,
	[ssr_reference] [nvarchar](30) NOT NULL,
	[ssr_ref_date] [date] NULL,
	[airline_pnr] [nvarchar](13) NULL,
	[gds_pnr] [nvarchar](13) NULL,
	[payment_mode] [nvarchar](20) NULL,
	[created_at] [datetimeoffset](7) NOT NULL,
	[updated_at] [datetimeoffset](7) NOT NULL,
	[customer_ledger_id] [int] NOT NULL,
	[original_ticket_id] [int] NOT NULL,
	[source_reschedule_ticket_id] [int] NULL,
	[payment_gateway_ref] [nvarchar](60) NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_ssr_ticket_company_invoice_no] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[invoice_number] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_ssr_ticket_company_ssr_ref] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[ssr_reference] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[SSR_AL_Tickets] ADD  DEFAULT ('Manual') FOR [booking_mode]
GO
ALTER TABLE [dbo].[SSR_AL_Tickets] ADD  DEFAULT ('SSR Updated') FOR [booking_status]
GO
ALTER TABLE [dbo].[SSR_AL_Tickets] ADD  DEFAULT ('INR') FOR [currency]
GO
ALTER TABLE [dbo].[SSR_AL_Tickets] ADD  DEFAULT ((1)) FOR [roe]
GO
ALTER TABLE [dbo].[SSR_AL_Tickets]  WITH CHECK ADD  CONSTRAINT [SSR_AL_Tickets_customer_ledger_id_af43f225_fk_Ledgers_id] FOREIGN KEY([customer_ledger_id])
REFERENCES [dbo].[Ledgers] ([id])
GO
ALTER TABLE [dbo].[SSR_AL_Tickets] CHECK CONSTRAINT [SSR_AL_Tickets_customer_ledger_id_af43f225_fk_Ledgers_id]
GO
ALTER TABLE [dbo].[SSR_AL_Tickets]  WITH CHECK ADD  CONSTRAINT [SSR_AL_Tickets_original_ticket_id_7710500e_fk_AL_Tickets_id] FOREIGN KEY([original_ticket_id])
REFERENCES [dbo].[AL_Tickets] ([id])
GO
ALTER TABLE [dbo].[SSR_AL_Tickets] CHECK CONSTRAINT [SSR_AL_Tickets_original_ticket_id_7710500e_fk_AL_Tickets_id]
GO
ALTER TABLE [dbo].[SSR_AL_Tickets]  WITH CHECK ADD  CONSTRAINT [SSR_AL_Tickets_source_reschedule_ticket_id_0997b713_fk_Rescheduled_Al_Ticket_id] FOREIGN KEY([source_reschedule_ticket_id])
REFERENCES [dbo].[Rescheduled_Al_Ticket] ([id])
GO
ALTER TABLE [dbo].[SSR_AL_Tickets] CHECK CONSTRAINT [SSR_AL_Tickets_source_reschedule_ticket_id_0997b713_fk_Rescheduled_Al_Ticket_id]
GO


GO

-- ==========================================================================
-- dbo.SupplierCommissionRules.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[SupplierCommissionRules]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[SupplierCommissionRules](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[rule_type] [nvarchar](20) NOT NULL,
	[office_id] [nvarchar](30) NOT NULL,
	[supplier_name] [nvarchar](200) NULL,
	[travel_type] [nvarchar](20) NULL,
	[airline_category] [nvarchar](10) NULL,
	[cabin] [nvarchar](30) NULL,
	[fare_type] [nvarchar](60) NULL,
	[calc_type] [nvarchar](12) NULL,
	[calc_pct] [decimal](14, 2) NOT NULL,
	[flat_amt] [decimal](14, 2) NOT NULL,
	[valid_upto] [date] NULL,
	[created_at] [datetime2](7) NOT NULL,
	[updated_at] [datetime2](7) NOT NULL,
	[comm_on] [nvarchar](20) NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[SupplierCommissionRules] ADD  DEFAULT ('Commission') FOR [rule_type]
GO
ALTER TABLE [dbo].[SupplierCommissionRules] ADD  DEFAULT ((0)) FOR [calc_pct]
GO
ALTER TABLE [dbo].[SupplierCommissionRules] ADD  DEFAULT ((0)) FOR [flat_amt]
GO
ALTER TABLE [dbo].[SupplierCommissionRules] ADD  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [dbo].[SupplierCommissionRules] ADD  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [dbo].[SupplierCommissionRules]  WITH CHECK ADD  CONSTRAINT [ck_supp_comm_rule_calc_type] CHECK  (([calc_type]='Flat' OR [calc_type]='Percentage'))
GO
ALTER TABLE [dbo].[SupplierCommissionRules] CHECK CONSTRAINT [ck_supp_comm_rule_calc_type]
GO


GO

-- ==========================================================================
-- dbo.UserMenuAccess.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[UserMenuAccess]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[UserMenuAccess](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[can_view] [bit] NOT NULL,
	[can_add] [bit] NOT NULL,
	[can_edit] [bit] NOT NULL,
	[can_delete] [bit] NOT NULL,
	[created_at] [datetimeoffset](7) NOT NULL,
	[updated_at] [datetimeoffset](7) NOT NULL,
	[created_by_id] [int] NULL,
	[menu_key] [nvarchar](60) NOT NULL,
	[user_id] [int] NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_user_menu_access] UNIQUE NONCLUSTERED 
(
	[user_id] ASC,
	[menu_key] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[UserMenuAccess]  WITH CHECK ADD  CONSTRAINT [UserMenuAccess_created_by_id_e2d61d3f_fk_AppUsers_id] FOREIGN KEY([created_by_id])
REFERENCES [dbo].[AppUsers] ([id])
GO
ALTER TABLE [dbo].[UserMenuAccess] CHECK CONSTRAINT [UserMenuAccess_created_by_id_e2d61d3f_fk_AppUsers_id]
GO
ALTER TABLE [dbo].[UserMenuAccess]  WITH CHECK ADD  CONSTRAINT [UserMenuAccess_menu_key_87b6c04a_fk_MenuMaster_menu_key] FOREIGN KEY([menu_key])
REFERENCES [dbo].[MenuMaster] ([menu_key])
GO
ALTER TABLE [dbo].[UserMenuAccess] CHECK CONSTRAINT [UserMenuAccess_menu_key_87b6c04a_fk_MenuMaster_menu_key]
GO
ALTER TABLE [dbo].[UserMenuAccess]  WITH CHECK ADD  CONSTRAINT [UserMenuAccess_user_id_bf86714d_fk_AppUsers_id] FOREIGN KEY([user_id])
REFERENCES [dbo].[AppUsers] ([id])
GO
ALTER TABLE [dbo].[UserMenuAccess] CHECK CONSTRAINT [UserMenuAccess_user_id_bf86714d_fk_AppUsers_id]
GO


GO

-- ==========================================================================
-- dbo.VoucherType.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[VoucherType]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[VoucherType](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[name] [nvarchar](100) NOT NULL,
	[alias_name] [nvarchar](100) NULL,
	[voucher_category] [nvarchar](20) NOT NULL,
	[is_active] [bit] NOT NULL,
	[number_method] [nvarchar](30) NOT NULL,
	[allow_additional_numbering] [bit] NOT NULL,
	[allow_effective_dates] [bit] NOT NULL,
	[allow_narration] [bit] NOT NULL,
	[an_width_of_invoice_number] [int] NULL,
	[an_prefill_with_zero] [bit] NOT NULL,
	[an_restart_applicable_from] [date] NULL,
	[an_restart_starting_number] [int] NULL,
	[an_restart_period] [nvarchar](10) NOT NULL,
	[an_prefix_details] [nvarchar](20) NULL,
	[an_suffix_details] [nvarchar](20) NULL,
	[created_at] [datetime2](7) NOT NULL,
	[updated_at] [datetime2](7) NOT NULL,
	[numbering_behaviour] [nvarchar](30) NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_voucher_type_company_name] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[name] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
ALTER TABLE [dbo].[VoucherType] ADD  DEFAULT ('General') FOR [voucher_category]
GO
ALTER TABLE [dbo].[VoucherType] ADD  DEFAULT ((1)) FOR [is_active]
GO
ALTER TABLE [dbo].[VoucherType] ADD  DEFAULT ('Automatic') FOR [number_method]
GO
ALTER TABLE [dbo].[VoucherType] ADD  DEFAULT ((0)) FOR [allow_additional_numbering]
GO
ALTER TABLE [dbo].[VoucherType] ADD  DEFAULT ((0)) FOR [allow_effective_dates]
GO
ALTER TABLE [dbo].[VoucherType] ADD  DEFAULT ((1)) FOR [allow_narration]
GO
ALTER TABLE [dbo].[VoucherType] ADD  DEFAULT ((0)) FOR [an_prefill_with_zero]
GO
ALTER TABLE [dbo].[VoucherType] ADD  DEFAULT ('None') FOR [an_restart_period]
GO
ALTER TABLE [dbo].[VoucherType] ADD  DEFAULT (sysutcdatetime()) FOR [created_at]
GO
ALTER TABLE [dbo].[VoucherType] ADD  DEFAULT (sysutcdatetime()) FOR [updated_at]
GO
ALTER TABLE [dbo].[VoucherType]  WITH CHECK ADD  CONSTRAINT [ck_voucher_type_an_restart_period] CHECK  (([an_restart_period]='None' OR [an_restart_period]='Yearly' OR [an_restart_period]='Monthly' OR [an_restart_period]='Weekly' OR [an_restart_period]='Daily'))
GO
ALTER TABLE [dbo].[VoucherType] CHECK CONSTRAINT [ck_voucher_type_an_restart_period]
GO
ALTER TABLE [dbo].[VoucherType]  WITH CHECK ADD  CONSTRAINT [ck_voucher_type_category] CHECK  (([voucher_category]='Credit Note' OR [voucher_category]='Debit Note' OR [voucher_category]='Contra' OR [voucher_category]='Receipt' OR [voucher_category]='Payment' OR [voucher_category]='Journal' OR [voucher_category]='General'))
GO
ALTER TABLE [dbo].[VoucherType] CHECK CONSTRAINT [ck_voucher_type_category]
GO
ALTER TABLE [dbo].[VoucherType]  WITH CHECK ADD  CONSTRAINT [ck_voucher_type_number_method] CHECK  (([number_method]='Automatic & Manual Override' OR [number_method]='Manual' OR [number_method]='Automatic'))
GO
ALTER TABLE [dbo].[VoucherType] CHECK CONSTRAINT [ck_voucher_type_number_method]
GO
ALTER TABLE [dbo].[VoucherType]  WITH CHECK ADD  CONSTRAINT [ck_voucher_type_numbering_behaviour] CHECK  (([numbering_behaviour]='Keep Original Numbers' OR [numbering_behaviour]='Restart Numbers'))
GO
ALTER TABLE [dbo].[VoucherType] CHECK CONSTRAINT [ck_voucher_type_numbering_behaviour]
GO


GO

-- ==========================================================================
-- dbo.Vouchers.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[Vouchers]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[Vouchers](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[company_id] [int] NOT NULL,
	[branch_name] [nvarchar](100) NULL,
	[voucher_type] [nvarchar](20) NOT NULL,
	[voucher_date] [date] NOT NULL,
	[narration] [nvarchar](250) NULL,
	[category] [nvarchar](20) NOT NULL,
	[voucher_no] [nvarchar](20) NULL,
	[total_debit] [numeric](16, 2) NOT NULL,
	[total_credit] [numeric](16, 2) NOT NULL,
	[lines_json] [nvarchar](max) NOT NULL,
	[created_at] [datetimeoffset](7) NOT NULL,
	[updated_at] [datetimeoffset](7) NOT NULL,
	[voucher_type_name] [nvarchar](100) NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY],
 CONSTRAINT [uq_voucher_company_no] UNIQUE NONCLUSTERED 
(
	[company_id] ASC,
	[voucher_no] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY] TEXTIMAGE_ON [PRIMARY]
GO
ALTER TABLE [dbo].[Vouchers]  WITH CHECK ADD  CONSTRAINT [Vouchers_lines_json_8b4c5b04_check] CHECK  ((isjson([lines_json])=(1)))
GO
ALTER TABLE [dbo].[Vouchers] CHECK CONSTRAINT [Vouchers_lines_json_8b4c5b04_check]
GO


GO

-- ==========================================================================
-- dbo.django_content_type.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[django_content_type]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[django_content_type](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[app_label] [nvarchar](100) NOT NULL,
	[model] [nvarchar](100) NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO


GO

-- ==========================================================================
-- dbo.django_migrations.Table.sql
-- ==========================================================================
USE [Accounting_DB]
GO
/****** Object:  Table [dbo].[django_migrations]    Script Date: 10/16/2026 10:47:30 AM ******/
SET ANSI_NULLS ON
GO
SET QUOTED_IDENTIFIER ON
GO
CREATE TABLE [dbo].[django_migrations](
	[id] [int] IDENTITY(1,1) NOT NULL,
	[app] [nvarchar](255) NOT NULL,
	[name] [nvarchar](255) NOT NULL,
	[applied] [datetimeoffset](7) NOT NULL,
PRIMARY KEY CLUSTERED 
(
	[id] ASC
)WITH (PAD_INDEX = OFF, STATISTICS_NORECOMPUTE = OFF, IGNORE_DUP_KEY = OFF, ALLOW_ROW_LOCKS = ON, ALLOW_PAGE_LOCKS = ON, OPTIMIZE_FOR_SEQUENTIAL_KEY = OFF) ON [PRIMARY]
) ON [PRIMARY]
GO
