SELECT
        hp.party_id                                                     ,
        hp.party_name                               AS customer_name    ,
        TO_CHAR(SYSDATE, 'DD-MON-YYYY')             AS Report_date      ,
        ooha.sold_to_org_id                         AS sold_to_party_id ,
        ooha.invoice_to_org_id                      AS bill_to_customer_id,
        ooha.order_number                                               ,
        TO_CHAR(ooha.ordered_date, 'DD-MON-YYYY')   AS order_date       ,
        wdd.released_status                                             ,
        oola.line_number                                                ,
        msi.segment1                                AS item_number      ,
        oola.order_quantity_uom                     AS ORDERED_UOM      ,
        oola.ordered_quantity                       AS ORDERED_QTY      ,
        DECODE(oola.cancelled_flag, 'Y', 'Y', 'N')  AS order_hold_flag  ,-- Mapped to Cancelled/Hold logic
        oola.unit_list_price                                            ,
        oola.unit_selling_price                                         ,
        oola.flow_status_code                       AS line_status      ,
        oola.flow_status_code                       AS "Fulfill Status" , -- Handled by OOLA in R12
        ooha.cust_po_number                         AS "PO Number"      ,
        oola.cust_po_number                         AS "PO Line"        ,
        'PO_REFERENCE'                              AS "Ref Type"       , 
        (
            SELECT
                    NVL(SUM(aps.amount_due_remaining), 0)
            FROM
                    ar_payment_schedules_all aps,
                    ra_customer_trx_all      rcta
            WHERE
                    aps.customer_trx_id              = rcta.customer_trx_id
            AND     rcta.interface_header_attribute1 = TO_CHAR(ooha.order_number)
        )                                           AS invoice_balance  ,
        TO_CHAR(nvl(oola.schedule_ship_date, oola.request_date), 'DD-MON-YYYY') AS schedule_ship_date,
        TO_CHAR(oola.actual_shipment_date, 'DD-MON-YYYY') AS ACTUAL_SHIP_DATE   ,
        DECODE(TRUNC(oola.schedule_ship_date), TRUNC(sysdate), 1, 0) AS today_arrival_qty,
        DECODE(wdd.released_status, 'B', 1, 0)      AS BACKORDER_FLAG   , -- 'B' represents Backordered in WSH
        (oola.ordered_quantity * oola.unit_selling_price) AS LINE_PRICE ,
        (
            SELECT
                    NVL(SUM(opa.adjusted_amount), 0)
            FROM
                    oe_price_adjustments opa
            WHERE
                    opa.line_id              = oola.line_id
            -- AND     UPPER(opa.name)          LIKE '%ADD%DISC%'
            AND     opa.list_line_type_code  = 'DIS'
        )                                           AS ADD_DISC,
        (
            SELECT
                    NVL(SUM(opa.adjusted_amount), 0)
            FROM
                    oe_price_adjustments opa
            WHERE
                    opa.line_id              = oola.line_id
            -- AND     UPPER(opa.name)          LIKE '%CASH%DISC%'
            AND     opa.list_line_type_code  = 'DIS'
        )                                           AS CASH_DISC,
        (
            SELECT
                    name
            FROM
                    oe_transaction_types_tl
            WHERE
                    transaction_type_id = ooha.order_type_id
            AND     language            = 'US'
        )                                           AS ORDER_TYPE,
        oola.shipping_method_code                   AS SHIPMENT_MODE, -- EBS stores this directly on the line/header
        /* Delayed Orders */
        (
            CASE
            WHEN
                    oola.schedule_ship_date IS NOT NULL
                    AND TRUNC(oola.schedule_ship_date) < TRUNC(NVL(oola.actual_shipment_date, SYSDATE))
            THEN
                    1
            ELSE
                    0
            END
        )                                           AS DELAYED_ORDER_FLAG,
        /* In-Transit Orders */
        (
            CASE
            WHEN
                    oola.actual_shipment_date IS NOT NULL
                    AND TRUNC(oola.schedule_ship_date) < TRUNC(SYSDATE)
                    AND wdd.released_status            = 'C' -- 'C' is Shipped
            THEN
                    1
            ELSE
                    0
            END
        )                                           AS in_transit_order_flag,
        /* Email Subquery (TCA Architecture remains very similar) */
        (
            SELECT
                    hcp.EMAIL_ADDRESS
            FROM
                    hz_cust_account_roles hcar,
                    hz_contact_points     hcp ,
                    hz_relationships      hr
            WHERE
                    hcar.RELATIONSHIP_ID   = hcp.relationship_id
            AND     hcp.RELATIONSHIP_ID    = hr.relationship_id
            AND     hcar.status            = 'A'
            AND     hcp.status             = 'A'
            AND     hcp.primary_flag       = 'Y'
            AND     hcp.contact_point_type = 'EMAIL'
            AND     hcar.cust_account_id   = ooha.sold_to_org_id
            AND     ROWNUM                 = 1
            AND     hr.OBJECT_TYPE         = 'ORGANIZATION'
        )                                           AS EMAIL
FROM
        OE_ORDER_HEADERS_ALL        ooha,
        OE_ORDER_LINES_ALL          oola,
        MTL_SYSTEM_ITEMS_B          msi,
        WSH_DELIVERY_DETAILS        wdd,
        HZ_CUST_ACCOUNTS            hcaa,
        HZ_PARTIES                  hp
WHERE
        ooha.header_id              = oola.header_id
AND     msi.inventory_item_id       = oola.inventory_item_id
AND     msi.organization_id         = oola.ship_from_org_id
AND     oola.line_id                = wdd.source_line_id(+)
AND     wdd.source_code(+)          = 'OE'
AND     hcaa.cust_account_id        = ooha.sold_to_org_id
AND     hp.party_id                 = hcaa.party_id
-- AND     ooha.ordered_date          >= TO_DATE('01-01-2005', 'DD-MM-YYYY')
-- AND     ooha.ordered_date          <= TO_DATE('01-01-2025', 'DD-MM-YYYY')
-- AND     hp.party_name               = :P_CUSTOMER_NAME
ORDER BY
        ooha.order_number,
        oola.line_number;