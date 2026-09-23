-- ============================================================================
-- TRAVEL AGENCY Accounting — MySQL Database Schema & Seed Script
-- Target Database: accounting_dep_db
-- ============================================================================

CREATE DATABASE IF NOT EXISTS `accounting_dep_db` 
    CHARACTER SET utf8mb4 
    COLLATE utf8mb4_unicode_ci;

USE `accounting_dep_db`;

SET FOREIGN_KEY_CHECKS = 0;

-- ----------------------------------------------------------------------------
-- Drop existing tables if re-running
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `TicketLines`;
DROP TABLE IF EXISTS `JournalVoucher`;
DROP TABLE IF EXISTS `Tickets`;
DROP TABLE IF EXISTS `Vouchers`;
DROP TABLE IF EXISTS `VoucherType`;
DROP TABLE IF EXISTS `MasterMapping`;
DROP TABLE IF EXISTS `FOPMaster`;
DROP TABLE IF EXISTS `PGMaster`;
DROP TABLE IF EXISTS `SupplierCommissionRules`;
DROP TABLE IF EXISTS `Ledgers`;
DROP TABLE IF EXISTS `Ledger_Groups`;
DROP TABLE IF EXISTS `CompanyMaster`;
DROP TABLE IF EXISTS `django_migrations`;

-- ----------------------------------------------------------------------------
-- 1. CompanyMaster
-- ----------------------------------------------------------------------------
CREATE TABLE `CompanyMaster` (
    `id`                      INT AUTO_INCREMENT PRIMARY KEY,
    `company_name`            VARCHAR(200) NOT NULL,
    `mailing_name`            VARCHAR(200) NULL,
    `address`                 LONGTEXT NULL,
    `country`                 VARCHAR(100) NOT NULL DEFAULT 'India',
    `state`                   VARCHAR(100) NULL,
    `pincode`                 VARCHAR(6) NULL,
    `telephone`               VARCHAR(20) NULL,
    `mobile`                  VARCHAR(10) NULL,
    `email`                   VARCHAR(200) NULL,
    `financial_year_from`     DATE NULL,
    `books_beginning_from`    DATE NULL,
    `gst_reg_type`            VARCHAR(20) NOT NULL DEFAULT 'Regular',
    `gst_no`                  VARCHAR(15) NULL,
    `cin_number`              VARCHAR(25) NULL,
    `tan_number`              VARCHAR(15) NULL,
    `hsn_sac`                 VARCHAR(20) NULL,
    `description`             LONGTEXT NULL,
    `created_at`              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `uq_company_master_name` UNIQUE (`company_name`),
    CONSTRAINT `ck_company_master_gst_reg_type` CHECK (`gst_reg_type` IN ('Regular', 'Composition', 'Unregistered', 'SEZ'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 2. Ledger_Groups — Chart of Accounts GROUP hierarchy
-- ----------------------------------------------------------------------------
CREATE TABLE `Ledger_Groups` (
    `id`              INT AUTO_INCREMENT PRIMARY KEY,
    `company_id`      INT NOT NULL,
    `name`            VARCHAR(100) NOT NULL,
    `code`            VARCHAR(20) NULL,
    `account_type`    VARCHAR(20) NOT NULL,
    `parent_id`       INT NULL,
    `is_group`        TINYINT(1) NOT NULL DEFAULT 1,
    `is_system`       TINYINT(1) NOT NULL DEFAULT 0,
    `created_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `fk_ledger_groups_parent` FOREIGN KEY (`parent_id`) REFERENCES `Ledger_Groups`(`id`) ON DELETE NO ACTION,
    CONSTRAINT `uq_ledger_groups_company_parent_name` UNIQUE (`company_id`, `parent_id`, `name`),
    CONSTRAINT `ck_ledger_groups_account_type` CHECK (`account_type` IN ('ASSET', 'LIABILITY', 'INCOME', 'EXPENSE', 'EQUITY')),
    KEY `ix_ledger_groups_company_id` (`company_id`),
    KEY `ix_ledger_groups_parent_id` (`parent_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 3. Ledgers — leaf accounts (customers, suppliers, banks, ...) under a group
-- ----------------------------------------------------------------------------
CREATE TABLE `Ledgers` (
    `id`                          INT AUTO_INCREMENT PRIMARY KEY,
    `company_id`                  INT NOT NULL,
    `name`                        VARCHAR(150) NOT NULL,
    `group_id`                    INT NOT NULL,
    `account_type`                VARCHAR(20) NOT NULL,
    `ledger_category`             VARCHAR(20) NOT NULL,
    `opening_balance`             DECIMAL(18,2) NOT NULL DEFAULT 0.00,
    `opening_balance_type`        VARCHAR(10) NOT NULL DEFAULT 'Debit',
    `bank_account_no`             VARCHAR(40) NULL,
    `bank_branch`                 VARCHAR(100) NULL,
    `ifsc_code`                   VARCHAR(15) NULL,
    `swift_code`                  VARCHAR(15) NULL,
    `alias_name`                  VARCHAR(100) NULL,
    `address_line1`               VARCHAR(150) NULL,
    `address_line2`               VARCHAR(150) NULL,
    `agent_id`                    VARCHAR(30) NULL,
    `maintain_balance_bill_wise`  VARCHAR(5) NULL,
    `place_of_supply`             VARCHAR(60) NULL,
    `city`                        VARCHAR(60) NULL,
    `pincode`                     VARCHAR(10) NULL,
    `state_name`                  VARCHAR(60) NULL,
    `gst_no`                      VARCHAR(20) NULL,
    `gst_registration_type`       VARCHAR(20) NULL,
    `pan_no`                      VARCHAR(15) NULL,
    `emirate`                     VARCHAR(30) NULL,
    `po_box_no`                   VARCHAR(20) NULL,
    `vat_trn_no`                  VARCHAR(20) NULL,
    `trade_license_no`            VARCHAR(30) NULL,
    `trade_license_expiry`        DATE NULL,
    `creditor_type`               VARCHAR(30) NULL,
    `supplier_code`               VARCHAR(30) NULL,
    `office_id`                   VARCHAR(30) NULL,
    `tax_category`                VARCHAR(10) NULL,
    `tax_type`                    VARCHAR(10) NULL,
    `gst_applicable`              TINYINT(1) NOT NULL DEFAULT 0,
    `gst_tax_type`                VARCHAR(10) NULL,
    `gst_percentage`              DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    `tds_applicable`              TINYINT(1) NOT NULL DEFAULT 0,
    `tds_percentage`              DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    `hsn_code`                    VARCHAR(15) NULL,
    `tcs_applicable`              TINYINT(1) NOT NULL DEFAULT 0,
    `tcs_percentage`              DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    `is_system`                   TINYINT(1) NOT NULL DEFAULT 0,
    `created_at`                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `fk_ledgers_group` FOREIGN KEY (`group_id`) REFERENCES `Ledger_Groups`(`id`) ON DELETE NO ACTION,
    CONSTRAINT `uq_ledger_company_name` UNIQUE (`company_id`, `name`),
    UNIQUE KEY `uq_ledger_agent_id` (`agent_id`),
    KEY `ix_ledgers_company_id` (`company_id`),
    KEY `ix_ledgers_group_id` (`group_id`),
    CONSTRAINT `ck_ledgers_account_type` CHECK (`account_type` IN ('ASSET', 'LIABILITY', 'INCOME', 'EXPENSE', 'EQUITY')),
    CONSTRAINT `ck_ledgers_opening_balance_type` CHECK (`opening_balance_type` IN ('Debit', 'Credit'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 4. Tickets — invoice/booking header
-- ----------------------------------------------------------------------------
CREATE TABLE `Tickets` (
    `id`                    INT AUTO_INCREMENT PRIMARY KEY,
    `company_id`            INT NOT NULL,
    `branch_name`           VARCHAR(100) NULL,
    `invoice_number`        VARCHAR(20) NOT NULL,
    `invoice_date`          DATE NOT NULL,
    `invoice_type`          VARCHAR(20) NULL,
    `booking_mode`          VARCHAR(20) NOT NULL DEFAULT 'Manual',
    `booking_type`          VARCHAR(30) NULL,
    `booking_status`        VARCHAR(20) NULL,
    `customer_ledger_id`    INT NOT NULL,
    `supplier_ledger_id`    INT NULL,
    `travel_type`           VARCHAR(20) NULL,
    `user_name`             VARCHAR(100) NULL,
    `currency`              VARCHAR(5) NOT NULL DEFAULT 'INR',
    `roe`                   DECIMAL(10,4) NOT NULL DEFAULT 1.0000,
    `booking_given_by`      VARCHAR(25) NULL,
    `booking_reference`     VARCHAR(30) NOT NULL,
    `booking_ref_date`      DATE NULL,
    `airline_pnr`           VARCHAR(13) NULL,
    `gds_pnr`               VARCHAR(13) NULL,
    `office_id`             VARCHAR(30) NULL,
    `payment_mode`          VARCHAR(20) NULL,
    `payment_gateway_ref`   VARCHAR(60) NULL,
    `airline_category`      VARCHAR(5) NULL,
    `created_at`            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `fk_tickets_customer` FOREIGN KEY (`customer_ledger_id`) REFERENCES `Ledgers`(`id`) ON DELETE NO ACTION,
    CONSTRAINT `fk_tickets_supplier` FOREIGN KEY (`supplier_ledger_id`) REFERENCES `Ledgers`(`id`) ON DELETE NO ACTION,
    CONSTRAINT `uq_ticket_company_invoice_no` UNIQUE (`company_id`, `invoice_number`),
    CONSTRAINT `uq_ticket_company_booking_ref` UNIQUE (`company_id`, `booking_reference`),
    CONSTRAINT `ck_tickets_invoice_type` CHECK (`invoice_type` IS NULL OR `invoice_type` IN ('Tax Invoice', 'Others')),
    CONSTRAINT `ck_tickets_booking_mode` CHECK (`booking_mode` IN ('Manual', 'Auto Push')),
    CONSTRAINT `ck_tickets_booking_status` CHECK (`booking_status` IS NULL OR `booking_status` IN ('Confirmed', 'Re-Scheduled')),
    CONSTRAINT `ck_tickets_travel_type` CHECK (`travel_type` IS NULL OR `travel_type` IN ('Domestic', 'International')),
    CONSTRAINT `ck_tickets_payment_mode` CHECK (`payment_mode` IS NULL OR `payment_mode` IN ('Top-up', 'Payment Gateway')),
    CONSTRAINT `ck_tickets_airline_category` CHECK (`airline_category` IS NULL OR `airline_category` IN ('LCC', 'FSC', 'OSC')),
    KEY `ix_tickets_company_id` (`company_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 5. TicketLines — passenger / segment rows per ticket
-- ----------------------------------------------------------------------------
CREATE TABLE `TicketLines` (
    `id`                    INT AUTO_INCREMENT PRIMARY KEY,
    `ticket_id`             INT NOT NULL,
    `airline_code`          VARCHAR(200) NULL,
    `airline_name`          VARCHAR(200) NULL,
    `airline_category`      VARCHAR(5) NULL,
    `flight_no`             VARCHAR(200) NULL,
    `ticket_no`             VARCHAR(30) NOT NULL,
    `passenger_name`        VARCHAR(50) NOT NULL,
    `pax_type`              VARCHAR(10) NOT NULL DEFAULT 'Adult',
    `sector`                VARCHAR(200) NULL,
    `travel_date`           VARCHAR(200) NULL,
    `cabin`                 VARCHAR(200) NULL,
    `travel_class`          VARCHAR(200) NULL,
    `fare_type`             VARCHAR(300) NULL,
    `basic_fare`            DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `yq`                    DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `yr`                    DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `k3_tax`                DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `tax_others`            DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `seat`                  DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `meal`                  DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `baggage`               DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `other_ssr`             DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `disc_on`               VARCHAR(20) NULL,
    `disc_type`             VARCHAR(12) NULL,
    `disc_value`            DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `tds_per`               DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    `pg_charges`            DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `markup`                DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `addl_markup`           DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `ssr_markup`            DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `service_fee`           DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `addl_service_fee`      DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `ssr_service_fee`       DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `gst_pct`               DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    `supp_comm_on`          VARCHAR(20) NULL,
    `supp_comm_type`        VARCHAR(12) NULL,
    `supp_comm_value`       DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `supp_tds_per`          DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    `supp_markup`           DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `supp_addl_markup`      DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `supp_service_fee`      DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `supp_addl_service_fee` DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `supp_gst_pct`          DECIMAL(5,2) NOT NULL DEFAULT 0.00,
    `total_billed`          DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `status`                VARCHAR(15) NOT NULL DEFAULT 'ISSUED',
    `supplier_ledger_id`    INT NULL,
    `office_id`             VARCHAR(30) NULL,
    `fop`                   VARCHAR(20) NULL,
    `card_number`           VARCHAR(40) NULL,
    `created_at`            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`            DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `fk_ticketlines_ticket` FOREIGN KEY (`ticket_id`) REFERENCES `Tickets`(`id`) ON DELETE CASCADE,
    CONSTRAINT `fk_ticketlines_supplier` FOREIGN KEY (`supplier_ledger_id`) REFERENCES `Ledgers`(`id`) ON DELETE NO ACTION,
    CONSTRAINT `uq_ticketline_ticket_no` UNIQUE (`ticket_no`),
    CONSTRAINT `ck_ticketlines_airline_category` CHECK (`airline_category` IS NULL OR `airline_category` IN ('LCC', 'FSC', 'OSC')),
    CONSTRAINT `ck_ticketlines_pax_type` CHECK (`pax_type` IN ('Adult', 'Child', 'Infant')),
    CONSTRAINT `ck_ticketlines_disc_type` CHECK (`disc_type` IS NULL OR `disc_type` IN ('Percentage', 'Flat', '')),
    CONSTRAINT `ck_ticketlines_supp_comm_type` CHECK (`supp_comm_type` IS NULL OR `supp_comm_type` IN ('Percentage', 'Flat', '')),
    CONSTRAINT `ck_ticketlines_status` CHECK (`status` IN ('ISSUED', 'REFUNDED', 'VOID', 'EXCHANGED')),
    CONSTRAINT `ck_ticketlines_fop` CHECK (`fop` IS NULL OR `fop` IN ('Own Card', 'Client Card', 'Cash', '')),
    KEY `ix_ticketlines_ticket_id` (`ticket_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 6. JournalVoucher — auto-posted GL entries for ticket JVs
-- ----------------------------------------------------------------------------
CREATE TABLE `JournalVoucher` (
    `id`                INT AUTO_INCREMENT PRIMARY KEY,
    `company_id`        INT NOT NULL,
    `branch_name`       VARCHAR(100) NULL,
    `voucher_type`      VARCHAR(20) NOT NULL DEFAULT 'Tax Invoice',
    `voucher_date`      DATE NOT NULL,
    `narration`         VARCHAR(250) NULL,
    `category`          VARCHAR(20) NOT NULL DEFAULT 'AIRLINE',
    `voucher_no`        VARCHAR(20) NULL,
    `source_ticket_id`  INT NULL,
    `total_debit`       DECIMAL(16,2) NOT NULL DEFAULT 0.00,
    `total_credit`      DECIMAL(16,2) NOT NULL DEFAULT 0.00,
    `lines_json`        LONGTEXT NOT NULL,
    `created_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `fk_journal_voucher_source_ticket` FOREIGN KEY (`source_ticket_id`) REFERENCES `Tickets`(`id`) ON DELETE SET NULL,
    CONSTRAINT `uq_journal_voucher_company_no` UNIQUE (`company_id`, `voucher_no`),
    KEY `journal_voucher_company_idx` (`company_id`),
    KEY `journal_voucher_ticket_idx` (`source_ticket_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 7. Vouchers — manually entered double-entry vouchers
-- ----------------------------------------------------------------------------
CREATE TABLE `Vouchers` (
    `id`                INT AUTO_INCREMENT PRIMARY KEY,
    `company_id`        INT NOT NULL,
    `branch_name`       VARCHAR(100) NULL,
    `voucher_type`      VARCHAR(20) NOT NULL DEFAULT 'Journal',
    `voucher_date`      DATE NOT NULL,
    `narration`         VARCHAR(250) NULL,
    `category`          VARCHAR(20) NOT NULL DEFAULT 'MANUAL',
    `voucher_no`        VARCHAR(20) NULL,
    `total_debit`       DECIMAL(16,2) NOT NULL DEFAULT 0.00,
    `total_credit`      DECIMAL(16,2) NOT NULL DEFAULT 0.00,
    `lines_json`        LONGTEXT NOT NULL,
    `created_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `uq_voucher_company_no` UNIQUE (`company_id`, `voucher_no`),
    CONSTRAINT `ck_vouchers_voucher_type` CHECK (`voucher_type` IN ('Journal', 'Contra', 'Payment', 'Receipt', 'Debit Note', 'Credit Note')),
    KEY `voucher_company_idx` (`company_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 7b. VoucherType — Custom Voucher Types and numbering formats
-- ----------------------------------------------------------------------------
CREATE TABLE `VoucherType` (
    `id`                               INT AUTO_INCREMENT PRIMARY KEY,
    `company_id`                       INT NOT NULL DEFAULT 1,
    `name`                             VARCHAR(150) NOT NULL,
    `alias_name`                       VARCHAR(100) NULL,
    `voucher_category`                 VARCHAR(100) NULL,
    `is_active`                        TINYINT(1) NOT NULL DEFAULT 1,
    `number_method`                    VARCHAR(50) NULL,
    `allow_additional_numbering`       TINYINT(1) NOT NULL DEFAULT 0,
    `allow_effective_dates`            TINYINT(1) NOT NULL DEFAULT 0,
    `allow_zero_value_transaction`     TINYINT(1) NOT NULL DEFAULT 0,
    `allow_narration`                  TINYINT(1) NOT NULL DEFAULT 1,
    `allow_narration_in_each_ledger`   TINYINT(1) NOT NULL DEFAULT 0,
    `an_width_of_invoice_number`       INT NULL,
    `an_prefill_with_zero`             TINYINT(1) NOT NULL DEFAULT 0,
    `an_restart_applicable_from`       DATE NULL,
    `an_restart_starting_number`       INT NULL,
    `an_restart_period`                VARCHAR(50) NULL,
    `an_prefix_details`                VARCHAR(100) NULL,
    `an_suffix_details`                VARCHAR(100) NULL,
    `created_at`                       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`                       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `uq_voucher_type_company_name` UNIQUE (`company_id`, `name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 8. SupplierCommissionRules
-- ----------------------------------------------------------------------------
CREATE TABLE `SupplierCommissionRules` (
    `id`                INT AUTO_INCREMENT PRIMARY KEY,
    `company_id`        INT NOT NULL,
    `rule_type`         VARCHAR(20) NOT NULL DEFAULT 'Commission',
    `office_id`         VARCHAR(30) NOT NULL,
    `supplier_name`     VARCHAR(200) NULL,
    `travel_type`       VARCHAR(20) NULL,
    `airline_category`  VARCHAR(10) NULL,
    `cabin`             VARCHAR(30) NULL,
    `fare_type`         VARCHAR(60) NULL,
    `comm_on`           VARCHAR(20) NULL,
    `calc_type`         VARCHAR(12) NULL,
    `calc_pct`          DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `flat_amt`          DECIMAL(14,2) NOT NULL DEFAULT 0.00,
    `valid_upto`        DATE NULL,
    `created_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `ck_supp_comm_rule_calc_type` CHECK (`calc_type` IS NULL OR `calc_type` IN ('Percentage', 'Flat')),
    KEY `ix_supp_comm_rules_company_office` (`company_id`, `office_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 9. MasterMapping
-- ----------------------------------------------------------------------------
CREATE TABLE `MasterMapping` (
    `id`                  INT AUTO_INCREMENT PRIMARY KEY,
    `company_id`          INT NOT NULL,
    `product_type`        VARCHAR(20) NOT NULL,
    `masters_category`    VARCHAR(40) NOT NULL,
    `masters_category_id` TINYINT NOT NULL,
    `field_name`          VARCHAR(60) NOT NULL,
    `ledger_id`           INT NOT NULL,
    `ledger_name`         VARCHAR(200) NULL,
    `effective_from`      DATE NOT NULL,
    `created_at`          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `fk_master_mapping_ledger` FOREIGN KEY (`ledger_id`) REFERENCES `Ledgers`(`id`) ON DELETE NO ACTION,
    CONSTRAINT `uq_master_mapping_field` UNIQUE (`company_id`, `product_type`, `field_name`),
    CONSTRAINT `ck_master_mapping_product_type` CHECK (`product_type` IN ('Airline', 'Hotel', 'Bus', 'Visa', 'Insurance', 'Rail')),
    CONSTRAINT `ck_master_mapping_masters_category` CHECK (`masters_category` IN (
        'Earnings From Customer', 'Earnings From Supplier',
        'Expenditure To Customer', 'Expenditure To Supplier', 'GST and TDS'
    )),
    CONSTRAINT `ck_master_mapping_masters_category_id` CHECK (`masters_category_id` BETWEEN 1 AND 5),
    KEY `ix_master_mapping_company_product` (`company_id`, `product_type`, `masters_category`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 10. FOPMaster
-- ----------------------------------------------------------------------------
CREATE TABLE `FOPMaster` (
    `id`                      INT AUTO_INCREMENT PRIMARY KEY,
    `company_id`              INT NOT NULL,
    `card_type`               VARCHAR(20) NOT NULL,
    `card_number`             VARCHAR(40) NOT NULL,
    `bank_name`               VARCHAR(100) NULL,
    `card_master_ledger_id`   INT NULL,
    `card_master_ledger_name` VARCHAR(200) NULL,
    `is_active`               TINYINT(1) NOT NULL DEFAULT 1,
    `created_at`              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`              DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `fk_fop_master_ledger` FOREIGN KEY (`card_master_ledger_id`) REFERENCES `Ledgers`(`id`) ON DELETE NO ACTION,
    CONSTRAINT `uq_fop_master_card_number` UNIQUE (`company_id`, `card_number`),
    CONSTRAINT `ck_fop_master_card_type` CHECK (`card_type` IN ('Own Card', 'Client Card')),
    KEY `ix_fop_master_company_type` (`company_id`, `card_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 11. PGMaster
-- ----------------------------------------------------------------------------
CREATE TABLE `PGMaster` (
    `id`                          INT AUTO_INCREMENT PRIMARY KEY,
    `company_id`                  INT NOT NULL,
    `gateway_name`                VARCHAR(100) NOT NULL,
    `payment_master_ledger_id`    INT NOT NULL,
    `payment_master_ledger_name`  VARCHAR(200) NULL,
    `pg_charges_master_ledger_id` INT NULL,
    `pg_charges_master_ledger_name` VARCHAR(200) NULL,
    `is_active`                   TINYINT(1) NOT NULL DEFAULT 1,
    `created_at`                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at`                  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT `fk_pg_master_ledger` FOREIGN KEY (`payment_master_ledger_id`) REFERENCES `Ledgers`(`id`) ON DELETE NO ACTION,
    CONSTRAINT `fk_pg_master_charges_ledger` FOREIGN KEY (`pg_charges_master_ledger_id`) REFERENCES `Ledgers`(`id`) ON DELETE NO ACTION,
    CONSTRAINT `uq_pg_master_gateway_name` UNIQUE (`company_id`, `gateway_name`),
    KEY `ix_pg_master_company` (`company_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- 12. django_migrations table
-- ----------------------------------------------------------------------------
CREATE TABLE `django_migrations` (
    `id`      INT AUTO_INCREMENT PRIMARY KEY,
    `app`     VARCHAR(255) NOT NULL,
    `name`    VARCHAR(255) NOT NULL,
    `applied` DATETIME(6) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;


-- ============================================================================
-- SEED DATA
-- ============================================================================

-- ----------------------------------------------------------------------------
-- S1. Company Master
-- ----------------------------------------------------------------------------
INSERT INTO `CompanyMaster` (`id`, `company_name`, `mailing_name`, `country`, `gst_reg_type`) VALUES
(1, 'Travel Agency India', 'Travel Agency India Pvt Ltd', 'India', 'Regular'),
(2, 'Travel Agency UAE', 'Travel Agency UAE LLC', 'United Arab Emirates', 'Regular')
ON DUPLICATE KEY UPDATE `company_name` = VALUES(`company_name`);

-- ----------------------------------------------------------------------------
-- S2. Ledger_Groups — Level 1 Top Groups (Assets, Liabilities, Income, Expenses)
-- ----------------------------------------------------------------------------
INSERT INTO `Ledger_Groups` (`company_id`, `name`, `code`, `account_type`, `parent_id`, `is_group`, `is_system`) VALUES
(1, 'Assets', '1000', 'ASSET', NULL, 1, 1),
(1, 'Liabilities', '2000', 'LIABILITY', NULL, 1, 1),
(1, 'Income', '4000', 'INCOME', NULL, 1, 1),
(1, 'Expenses', '5000', 'EXPENSE', NULL, 1, 1),
(2, 'Assets', '1000', 'ASSET', NULL, 1, 1),
(2, 'Liabilities', '2000', 'LIABILITY', NULL, 1, 1),
(2, 'Income', '4000', 'INCOME', NULL, 1, 1),
(2, 'Expenses', '5000', 'EXPENSE', NULL, 1, 1);

-- ----------------------------------------------------------------------------
-- S3. Ledger_Groups — Level 2 Primary Sub-Groups
-- ----------------------------------------------------------------------------
INSERT INTO `Ledger_Groups` (`company_id`, `name`, `code`, `account_type`, `parent_id`, `is_group`, `is_system`)
SELECT c.company_id, v.name, v.code, v.account_type, p.id, 1, 1
FROM (SELECT 1 AS company_id UNION ALL SELECT 2) AS c
JOIN (
    SELECT 'Capital Account' AS name, '2100' AS code, 'LIABILITY' AS account_type, 'Liabilities' AS parent_name UNION ALL
    SELECT 'Loans (Liability)', '2200', 'LIABILITY', 'Liabilities' UNION ALL
    SELECT 'Current Liabilities', '2300', 'LIABILITY', 'Liabilities' UNION ALL
    SELECT 'Fixed Assets', '1100', 'ASSET', 'Assets' UNION ALL
    SELECT 'Investments', '1200', 'ASSET', 'Assets' UNION ALL
    SELECT 'Current Assets', '1300', 'ASSET', 'Assets' UNION ALL
    SELECT 'Sales Accounts', '4100', 'INCOME', 'Income' UNION ALL
    SELECT 'Direct Income', '4200', 'INCOME', 'Income' UNION ALL
    SELECT 'Indirect Income', '4300', 'INCOME', 'Income' UNION ALL
    SELECT 'Purchase Accounts', '5100', 'EXPENSE', 'Expenses' UNION ALL
    SELECT 'Direct Expenses', '5200', 'EXPENSE', 'Expenses' UNION ALL
    SELECT 'Indirect Expenses', '5300', 'EXPENSE', 'Expenses'
) AS v
JOIN `Ledger_Groups` p ON p.company_id = c.company_id AND p.name = v.parent_name COLLATE utf8mb4_unicode_ci AND p.parent_id IS NULL;

-- ----------------------------------------------------------------------------
-- S4. Ledger_Groups — Level 3 Sub-Groups
-- ----------------------------------------------------------------------------
INSERT INTO `Ledger_Groups` (`company_id`, `name`, `code`, `account_type`, `parent_id`, `is_group`, `is_system`)
SELECT c.company_id, v.name, v.code, v.account_type, p.id, 1, 1
FROM (SELECT 1 AS company_id UNION ALL SELECT 2) AS c
JOIN (
    SELECT 'Secured Loans' AS name, '2210' AS code, 'LIABILITY' AS account_type, 'Loans (Liability)' AS parent_name UNION ALL
    SELECT 'Unsecured Loans', '2220', 'LIABILITY', 'Loans (Liability)' UNION ALL
    SELECT 'Sundry Creditors', '2310', 'LIABILITY', 'Current Liabilities' UNION ALL
    SELECT 'Duties & Taxes', '2320', 'LIABILITY', 'Current Liabilities' UNION ALL
    SELECT 'Provisions', '2330', 'LIABILITY', 'Current Liabilities' UNION ALL
    SELECT 'Sundry Debtors', '1310', 'ASSET', 'Current Assets' UNION ALL
    SELECT 'Bank Accounts', '1320', 'ASSET', 'Current Assets' UNION ALL
    SELECT 'Cash-in-hand', '1330', 'ASSET', 'Current Assets' UNION ALL
    SELECT 'Deposits (Asset)', '1340', 'ASSET', 'Current Assets' UNION ALL
    SELECT 'Stock-in-hand', '1350', 'ASSET', 'Current Assets' UNION ALL
    SELECT 'Tax Assets', '1360', 'ASSET', 'Current Assets'
) AS v
JOIN `Ledger_Groups` p ON p.company_id = c.company_id AND p.name = v.parent_name COLLATE utf8mb4_unicode_ci AND p.parent_id IS NOT NULL;

-- ----------------------------------------------------------------------------
-- S5. Ledgers — Base System Leaf Accounts
-- ----------------------------------------------------------------------------
INSERT INTO `Ledgers` (
    `company_id`, `name`, `group_id`, `account_type`, `ledger_category`, 
    `opening_balance`, `opening_balance_type`, `is_system`
)
SELECT 
    c.company_id, v.name, g.id, v.account_type, v.ledger_category, 0.00, 'Debit', 1
FROM (SELECT 1 AS company_id UNION ALL SELECT 2) AS c
JOIN (
    SELECT 'Markup A/c' AS name, 'Direct Income' AS group_name, 'INCOME' AS account_type, 'GENERAL' AS ledger_category UNION ALL
    SELECT 'Addl Markup A/c', 'Direct Income', 'INCOME', 'GENERAL' UNION ALL
    SELECT 'SSR Markup A/c', 'Direct Income', 'INCOME', 'GENERAL' UNION ALL
    SELECT 'Service Fee A/c', 'Direct Income', 'INCOME', 'GENERAL' UNION ALL
    SELECT 'Addl Service Fee A/c', 'Direct Income', 'INCOME', 'GENERAL' UNION ALL
    SELECT 'Commission A/c', 'Indirect Income', 'INCOME', 'GENERAL' UNION ALL
    SELECT 'Discount A/c', 'Indirect Expenses', 'EXPENSE', 'GENERAL' UNION ALL
    SELECT 'IGST A/c', 'Duties & Taxes', 'LIABILITY', 'TAX' UNION ALL
    SELECT 'CGST A/c', 'Duties & Taxes', 'LIABILITY', 'TAX' UNION ALL
    SELECT 'SGST A/c', 'Duties & Taxes', 'LIABILITY', 'TAX' UNION ALL
    SELECT 'Discount TDS A/c', 'Duties & Taxes', 'LIABILITY', 'TAX' UNION ALL
    SELECT 'Commission TDS A/c', 'Duties & Taxes', 'LIABILITY', 'TAX' UNION ALL
    SELECT 'HDFC Corporate Credit Card', 'Current Liabilities', 'LIABILITY', 'BANK' UNION ALL
    SELECT 'ICICI Business Card', 'Current Liabilities', 'LIABILITY', 'BANK' UNION ALL
    SELECT 'SBI Commercial Card', 'Current Liabilities', 'LIABILITY', 'BANK' UNION ALL
    SELECT 'Axis Corporate Card', 'Current Liabilities', 'LIABILITY', 'BANK' UNION ALL
    SELECT 'Amex Business Card', 'Current Liabilities', 'LIABILITY', 'BANK' UNION ALL
    SELECT 'IndiGo Airlines', 'Sundry Creditors', 'LIABILITY', 'SUPPLIER' UNION ALL
    SELECT 'Air India', 'Sundry Creditors', 'LIABILITY', 'SUPPLIER' UNION ALL
    SELECT 'SpiceJet', 'Sundry Creditors', 'LIABILITY', 'SUPPLIER' UNION ALL
    SELECT 'Emirates', 'Sundry Creditors', 'LIABILITY', 'SUPPLIER' UNION ALL
    SELECT 'ABC Travels', 'Sundry Debtors', 'ASSET', 'CUSTOMER'
) AS v
JOIN `Ledger_Groups` g ON g.company_id = c.company_id AND g.name = v.group_name COLLATE utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- S6. MasterMapping — Airline Product Mappings
-- ----------------------------------------------------------------------------
INSERT INTO `MasterMapping` (
    `company_id`, `product_type`, `masters_category`, `masters_category_id`, 
    `field_name`, `ledger_id`, `ledger_name`, `effective_from`
)
SELECT 
    c.company_id, 'Airline', m.masters_category, m.masters_category_id, 
    m.field_name, l.id, l.name, CURDATE()
FROM (SELECT 1 AS company_id UNION ALL SELECT 2) AS c
JOIN (
    SELECT 'Earnings From Customer' AS masters_category, 1 AS masters_category_id, 'Markup A/c' AS field_name, 'Markup A/c' AS match_ledger_name UNION ALL
    SELECT 'Earnings From Customer', 1, 'Addl Markup A/c', 'Addl Markup A/c' UNION ALL
    SELECT 'Earnings From Customer', 1, 'SSR Markup A/c', 'SSR Markup A/c' UNION ALL
    SELECT 'Earnings From Customer', 1, 'Service Fee A/c', 'Service Fee A/c' UNION ALL
    SELECT 'Earnings From Customer', 1, 'Addl Service Fee A/c', 'Addl Service Fee A/c' UNION ALL
    SELECT 'Earnings From Customer', 1, 'SSR Service Fee A/c', 'Service Fee A/c' UNION ALL
    SELECT 'Earnings From Supplier', 2, 'Commission A/c', 'Commission A/c' UNION ALL
    SELECT 'Expenditure To Customer', 3, 'Discount A/c', 'Discount A/c' UNION ALL
    SELECT 'Expenditure To Supplier', 4, 'Supplier Markup A/c', 'Markup A/c' UNION ALL
    SELECT 'Expenditure To Supplier', 4, 'Supplier Addl Markup A/c', 'Addl Markup A/c' UNION ALL
    SELECT 'Expenditure To Supplier', 4, 'Supplier Service Fee A/c', 'Service Fee A/c' UNION ALL
    SELECT 'Expenditure To Supplier', 4, 'Supplier Addl Service Fee A/c', 'Addl Service Fee A/c' UNION ALL
    SELECT 'GST and TDS', 5, 'Output IGST A/c', 'IGST A/c' UNION ALL
    SELECT 'GST and TDS', 5, 'Output CGST A/c', 'CGST A/c' UNION ALL
    SELECT 'GST and TDS', 5, 'Output SGST A/c', 'SGST A/c' UNION ALL
    SELECT 'GST and TDS', 5, 'Discount TDS A/c', 'Discount TDS A/c' UNION ALL
    SELECT 'GST and TDS', 5, 'Commission TDS A/c', 'Commission TDS A/c' UNION ALL
    SELECT 'GST and TDS', 5, 'Input IGST A/c', 'IGST A/c' UNION ALL
    SELECT 'GST and TDS', 5, 'Input CGST A/c', 'CGST A/c' UNION ALL
    SELECT 'GST and TDS', 5, 'Input SGST A/c', 'SGST A/c'
) AS m
JOIN `Ledgers` l ON l.company_id = c.company_id AND l.name = m.match_ledger_name COLLATE utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- S7. FOPMaster — Form of Payment Cards Registry
-- ----------------------------------------------------------------------------
INSERT INTO `FOPMaster` (`company_id`, `card_type`, `card_number`, `bank_name`, `card_master_ledger_id`, `card_master_ledger_name`, `is_active`)
SELECT 
    c.company_id, card.card_type, card.card_number, card.bank_name, l.id, l.name, 1
FROM (SELECT 1 AS company_id UNION ALL SELECT 2) AS c
JOIN (
    SELECT 'Own Card' AS card_type, '4111-2222-3333-4444' AS card_number, 'HDFC Bank' AS bank_name, 'HDFC Corporate Credit Card' AS match_ledger_name UNION ALL
    SELECT 'Own Card', '5200-8888-9999-1111', 'ICICI Bank', 'ICICI Business Card' UNION ALL
    SELECT 'Own Card', '4532-7777-6666-5555', 'SBI Bank', 'SBI Commercial Card' UNION ALL
    SELECT 'Own Card', '4386-3333-2222-1111', 'Axis Bank', 'Axis Corporate Card' UNION ALL
    SELECT 'Own Card', '3782-8224-6310-0050', 'Amex', 'Amex Business Card' UNION ALL
    SELECT 'Client Card', '4000-1234-5678-9010', 'Client Bank', 'HDFC Corporate Credit Card'
) AS card
JOIN `Ledgers` l ON l.company_id = c.company_id AND l.name = card.match_ledger_name COLLATE utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- S8. PGMaster — Payment Gateways Registry
-- ----------------------------------------------------------------------------
INSERT INTO `PGMaster` (`company_id`, `gateway_name`, `payment_master_ledger_id`, `payment_master_ledger_name`, `is_active`)
SELECT 
    c.company_id, pg.gateway_name, l.id, l.name, 1
FROM (SELECT 1 AS company_id UNION ALL SELECT 2) AS c
JOIN (
    SELECT 'Razorpay' AS gateway_name, 'HDFC Corporate Credit Card' AS match_ledger_name UNION ALL
    SELECT 'PayU', 'ICICI Business Card' UNION ALL
    SELECT 'Stripe', 'Axis Corporate Card' UNION ALL
    SELECT 'CCAvenue', 'SBI Commercial Card'
) AS pg
JOIN `Ledgers` l ON l.company_id = c.company_id AND l.name = pg.match_ledger_name COLLATE utf8mb4_unicode_ci;

-- ----------------------------------------------------------------------------
-- S9. SupplierCommissionRules — Supplier Master Commission Rules
-- ----------------------------------------------------------------------------
INSERT INTO `SupplierCommissionRules` (
    `company_id`, `rule_type`, `office_id`, `supplier_name`, `travel_type`, 
    `airline_category`, `cabin`, `fare_type`, `comm_on`, `calc_type`, 
    `calc_pct`, `flat_amt`, `valid_upto`
)
SELECT 
    c.company_id, r.rule_type, r.office_id, r.supplier_name, r.travel_type,
    r.airline_category, r.cabin, r.fare_type, r.comm_on, r.calc_type,
    r.calc_pct, r.flat_amt, '2026-12-31'
FROM (SELECT 1 AS company_id UNION ALL SELECT 2) AS c
JOIN (
    SELECT 'Commission' AS rule_type, 'DEL123' AS office_id, 'IndiGo Airlines' AS supplier_name, 'DOM' AS travel_type, 'LCC' AS airline_category, 'Economy' AS cabin, 'Normal' AS fare_type, 'Basic + YQ' AS comm_on, 'Percentage' AS calc_type, 3.50 AS calc_pct, 0.00 AS flat_amt UNION ALL
    SELECT 'Commission', 'BOM456', 'Air India', 'INT', 'FSC', 'Economy', 'Flexi', 'Basic', 'Percentage', 4.00, 0.00 UNION ALL
    SELECT 'Commission', 'DXB789', 'Emirates', 'INT', 'FSC', 'Business', 'Flexi', 'Basic', 'Percentage', 5.00, 0.00 UNION ALL
    SELECT 'Commission', 'DEL123', 'SpiceJet', 'DOM', 'LCC', 'Economy', 'Normal', 'Basic', 'Flat', 0.00, 250.00
) AS r;

-- ----------------------------------------------------------------------------
-- S10. Django Migrations Sync
-- ----------------------------------------------------------------------------
INSERT INTO `django_migrations` (`app`, `name`, `applied`) VALUES
('accounting', '0001_initial', NOW()),
('accounting', '0002_ticket_ticketline_voucher', NOW()),
('accounting', '0003_ticketline_supplier_fields', NOW()),
('accounting', '0004_ledger_untracked_fields', NOW()),
('accounting', '0005_ticketline_supplier_commission', NOW()),
('accounting', '0006_ticketline_fop_add_cash', NOW()),
('accounting', '0007_rename_supp_disc_on_ticketline_supp_comm_on_and_more', NOW()),
('accounting', '0008_ledger_remove_airline_code', NOW()),
('accounting', '0009_ticketline_multi_sector', NOW()),
('accounting', '0010_ticketline_ssr_markup_ticketline_ssr_service_fee', NOW()),
('accounting', '0011_suppliercommissionrule', NOW()),
('accounting', '0012_suppliercommissionrule_comm_on', NOW()),
('accounting', '0013_mastermapping_mastermapping_uq_master_mapping_field', NOW()),
('accounting', '0014_mastermapping_masters_category_id', NOW()),
('accounting', '0015_fopmaster_fopmaster_uq_fop_master_card_number', NOW()),
('accounting', '0016_ticketline_card_number', NOW()),
('accounting', '0017_ticket_payment_gateway_ref', NOW()),
('accounting', '0018_pgmaster_pgmaster_uq_pg_master_gateway_name', NOW()),
('accounting', '0019_ticketline_supp_addl_markup_and_more', NOW()),
('accounting', '0020_alter_mastermapping_masters_category', NOW()),
('accounting', '0021_fopmaster_bank_name', NOW()),
('accounting', '0022_alter_ticketline_airline_code_and_more', NOW()),
('accounting', '0023_alter_ticketline_passenger_name', NOW()),
('accounting', '0024_alter_fopmaster_card_master_ledger', NOW()),
('accounting', '0025_companymaster', NOW()),
('accounting', '0026_remove_companymaster_is_active', NOW()),
('accounting', '0027_pgmaster_pg_charges_master_ledger_and_more', NOW()),
('accounting', '0028_ticketline_pg_charges', NOW()),
('accounting', '0029_split_voucher_journalvoucher', NOW());

-- ----------------------------------------------------------------------------
-- Verification Queries
-- ----------------------------------------------------------------------------
SELECT 'CompanyMaster' AS `table`, COUNT(*) AS `count` FROM `CompanyMaster`
UNION ALL
SELECT 'Ledger_Groups', COUNT(*) FROM `Ledger_Groups`
UNION ALL
SELECT 'Ledgers', COUNT(*) FROM `Ledgers`
UNION ALL
SELECT 'MasterMapping', COUNT(*) FROM `MasterMapping`
UNION ALL
SELECT 'FOPMaster', COUNT(*) FROM `FOPMaster`
UNION ALL
SELECT 'PGMaster', COUNT(*) FROM `PGMaster`
UNION ALL
SELECT 'SupplierCommissionRules', COUNT(*) FROM `SupplierCommissionRules`
UNION ALL
SELECT 'JournalVoucher', COUNT(*) FROM `JournalVoucher`
UNION ALL
SELECT 'Vouchers', COUNT(*) FROM `Vouchers`
UNION ALL
SELECT 'Tickets', COUNT(*) FROM `Tickets`
UNION ALL
SELECT 'TicketLines', COUNT(*) FROM `TicketLines`;
