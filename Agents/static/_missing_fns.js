
function wizAutoLoadSites() {
    var wiz = document.getElementById('create-wizard');
    var html = '<h3>➕ Create New Sales Order</h3>';
    html += '<p style="color:#6b7280;font-size:0.85rem;margin-bottom:12px;">Step 4 of 6: Select Ship-To Site (Customer: <b>' + escapeHtml(_createWizard.customer_name) + '</b>)</p>';
    html += '<div id="wiz-cust-results"><p style="color:#6b7280;">Loading ship-to sites...</p></div>';
    wiz.innerHTML = html;
    scroll();

    fetch('/api/lookup-customer-sites?cust_account_id=' + _createWizard.cust_account_id)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var results = document.getElementById('wiz-cust-results');
            if (data.error) { results.innerHTML = '<p style="color:#991b1b;">Error: ' + escapeHtml(data.error) + '</p>'; return; }
            if (!data.sites || data.sites.length === 0) {
                results.innerHTML = '<p style="color:#991b1b;">No active ship-to sites found. Please select customer manually.</p>';
                setTimeout(function() { wizShowCustomerSearch(); }, 1200);
                return;
            }
            if (data.sites.length === 1) {
                var site = data.sites[0];
                _createWizard.sold_to_org_id = site.sold_to_org_id;
                _createWizard.ship_to_org_id = site.ship_to_org_id;
                results.innerHTML = '<p style="color:#065f46;">Auto-selected site: ' + escapeHtml(site.location) + ' - ' + escapeHtml(site.address) + '</p>';
                setTimeout(function() { wizShowPriceList(); }, 700);
                return;
            }
            var table = '<p style="font-weight:600;margin-bottom:6px;">Select a Ship-To site:</p>';
            table += '<table class="order-table" style="font-size:0.82rem;"><thead><tr><th>#</th><th>Location</th><th>Address</th></tr></thead><tbody>';
            for (var i = 0; i < data.sites.length; i++) {
                var s = data.sites[i];
                table += '<tr style="cursor:pointer;" onclick="wizSelectSite(' + s.sold_to_org_id + ',' + s.ship_to_org_id + ')">';
                table += '<td>' + (i + 1) + '</td><td><b>' + escapeHtml(s.location) + '</b></td><td>' + escapeHtml(s.address) + '</td></tr>';
            }
            table += '</tbody></table>';
            table += '<div class="form-actions" style="margin-top:10px;"><button class="btn-cancel" onclick="cancelCreateOrder(this)">Cancel</button></div>';
            results.innerHTML = table;
            scroll();
        })
        .catch(function(err) {
            document.getElementById('wiz-cust-results').innerHTML = '<p style="color:#991b1b;">Network error: ' + escapeHtml(err.message) + '</p>';
        });
}

window.wizStep1Next = function() {
    var cpo = document.getElementById('wiz-cpo').value.trim();
    if (!cpo) { alert('Customer PO is required.'); return; }
    _createWizard.cust_po_number = cpo;
    _createWizard.step = 2;
    wizShowItemSearch();
};

function wizShowItemSearch() {
    var wiz = document.getElementById('create-wizard');
    var html = '<h3>➕ Create New Sales Order</h3>';
    html += '<p style="color:#6b7280;font-size:0.85rem;margin-bottom:12px;">Step 2 of 6: Search and Select Item</p>';
    html += '<div class="form-grid"><div class="full"><label>Item Name / Prefix</label>';
    html += '<input type="text" id="wiz-item-search" placeholder="e.g. AS" onkeydown="if(event.key===\'Enter\')wizSearchItems(0)"></div></div>';
    html += '<div class="form-actions" style="margin-bottom:10px;"><button class="btn-submit" onclick="wizSearchItems(0)">Search</button><button class="btn-cancel" onclick="cancelCreateOrder(this)">Cancel</button></div>';
    html += '<div id="wiz-item-results"></div>';
    wiz.innerHTML = html;
    scroll();
}

window.wizSearchItems = function(offset) {
    var search = document.getElementById('wiz-item-search').value.trim();
    if (!search) { alert('Enter an item name or prefix to search.'); return; }
    _createWizard.itemSearch = search;
    _createWizard.itemOffset = offset;
    var results = document.getElementById('wiz-item-results');
    results.innerHTML = '<p style="color:#6b7280;">Searching...</p>';

    fetch('/api/lookup-items?search=' + encodeURIComponent(search) + '&offset=' + offset)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) { results.innerHTML = '<p style="color:#991b1b;">Error: ' + escapeHtml(data.error) + '</p>'; return; }
            if (!data.items || data.items.length === 0) { results.innerHTML = '<p style="color:#991b1b;">No items found matching "' + escapeHtml(search) + '".</p>'; return; }
            var html = '<table class="order-table" style="font-size:0.82rem;"><thead><tr><th>#</th><th>Item</th><th>Description</th></tr></thead><tbody>';
            for (var i = 0; i < data.items.length; i++) {
                var it = data.items[i];
                html += '<tr style="cursor:pointer;" onclick="wizSelectItem(' + it.inventory_item_id + ',\'' + escapeHtml(it.segment1).replace(/'/g, "\\'") + '\')">';
                html += '<td>' + (offset + i + 1) + '</td><td><b>' + escapeHtml(it.segment1) + '</b></td><td>' + escapeHtml(it.description) + '</td></tr>';
            }
            html += '</tbody></table>';
            var nav = '<div style="margin-top:8px;">';
            if (offset > 0) nav += '<button class="btn-cancel" onclick="wizSearchItems(' + (offset - MAX_CHOICES) + ')">Prev</button> ';
            if (data.has_more) nav += '<button class="btn-cancel" onclick="wizSearchItems(' + (offset + MAX_CHOICES) + ')">Next</button>';
            nav += '</div>';
            results.innerHTML = html + nav;
            scroll();
        })
        .catch(function(err) { results.innerHTML = '<p style="color:#991b1b;">Network error: ' + escapeHtml(err.message) + '</p>'; });
};

window.wizSelectItem = function(itemId, segment1) {
    _createWizard.inventory_item_id = itemId;
    _createWizard.ordered_item = segment1;
    _createWizard.step = 3;
    wizShowQuantity();
};

function wizShowQuantity() {
    var wiz = document.getElementById('create-wizard');
    var html = '<h3>➕ Create New Sales Order</h3>';
    html += '<p style="color:#6b7280;font-size:0.85rem;margin-bottom:12px;">Step 3 of 6: Enter Quantity (Item: <b>' + escapeHtml(_createWizard.ordered_item) + '</b>)</p>';
    html += '<div class="form-grid"><div class="full"><label>Quantity</label><input type="number" id="wiz-qty" value="1" min="1" step="0.01"></div></div>';
    html += '<div class="form-actions"><button class="btn-submit" onclick="wizStep3Next()">Next</button><button class="btn-cancel" onclick="cancelCreateOrder(this)">Cancel</button></div>';
    wiz.innerHTML = html;
    scroll();
}

window.wizStep3Next = function() {
    var qty = parseFloat(document.getElementById('wiz-qty').value);
    if (!qty || qty <= 0) { alert('Quantity must be greater than 0.'); return; }
    _createWizard.ordered_quantity = qty;
    _createWizard.step = 4;
    wizShowCustomerSearch();
};

function wizShowCustomerSearch() {
    var wiz = document.getElementById('create-wizard');
    var html = '<h3>➕ Create New Sales Order</h3>';
    html += '<p style="color:#6b7280;font-size:0.85rem;margin-bottom:12px;">Step 4 of 6: Select Customer</p>';
    html += '<div class="form-grid"><div class="full"><label>Search Customer by Name</label>';
    html += '<input type="text" id="wiz-cust-search" placeholder="e.g. Vision" onkeydown="if(event.key===\'Enter\')wizSearchCustomers(0)"></div></div>';
    html += '<div class="form-actions" style="margin-bottom:10px;"><button class="btn-submit" onclick="wizSearchCustomers(0)">Search by Name</button><button class="btn-cancel" style="background:#e0e7ff;color:#3730a3;" onclick="wizSearchCustomersByItem(0)">Suggest by Item</button><button class="btn-cancel" onclick="cancelCreateOrder(this)">Cancel</button></div>';
    html += '<div id="wiz-cust-results"></div>';
    wiz.innerHTML = html;
    scroll();
}

window.wizSearchCustomers = function(offset) {
    var search = document.getElementById('wiz-cust-search').value.trim();
    if (!search) { alert('Enter a customer name to search.'); return; }
    var results = document.getElementById('wiz-cust-results');
    results.innerHTML = '<p style="color:#6b7280;">Searching...</p>';
    fetch('/api/lookup-customers?search=' + encodeURIComponent(search) + '&offset=' + offset)
        .then(function(r) { return r.json(); })
        .then(function(data) { wizRenderCustomers(data, offset, 'search'); })
        .catch(function(err) { results.innerHTML = '<p style="color:#991b1b;">Network error: ' + escapeHtml(err.message) + '</p>'; });
};

window.wizSearchCustomersByItem = function(offset) {
    var results = document.getElementById('wiz-cust-results');
    results.innerHTML = '<p style="color:#6b7280;">Looking up customers for item ' + escapeHtml(_createWizard.ordered_item) + '...</p>';
    fetch('/api/lookup-customers?item_id=' + _createWizard.inventory_item_id + '&offset=' + offset)
        .then(function(r) { return r.json(); })
        .then(function(data) { wizRenderCustomers(data, offset, 'item'); })
        .catch(function(err) { results.innerHTML = '<p style="color:#991b1b;">Network error: ' + escapeHtml(err.message) + '</p>'; });
};

function wizRenderCustomers(data, offset, mode) {
    var results = document.getElementById('wiz-cust-results');
    if (data.error) { results.innerHTML = '<p style="color:#991b1b;">Error: ' + escapeHtml(data.error) + '</p>'; return; }
    if (!data.customers || data.customers.length === 0) { results.innerHTML = '<p style="color:#991b1b;">No customers found.</p>'; return; }
    var html = '<table class="order-table" style="font-size:0.82rem;"><thead><tr><th>#</th><th>Customer Name</th><th>Account #</th></tr></thead><tbody>';
    for (var i = 0; i < data.customers.length; i++) {
        var c = data.customers[i];
        html += '<tr style="cursor:pointer;" onclick="wizSelectCustomer(' + c.cust_account_id + ',\'' + escapeHtml(c.customer_name).replace(/'/g, "\\'") + '\')">';
        html += '<td>' + (offset + i + 1) + '</td><td><b>' + escapeHtml(c.customer_name) + '</b></td><td>' + escapeHtml(c.account_number) + '</td></tr>';
    }
    html += '</tbody></table>';
    var nav = '<div style="margin-top:8px;">';
    var fn = mode === 'item' ? 'wizSearchCustomersByItem' : 'wizSearchCustomers';
    if (offset > 0) nav += '<button class="btn-cancel" onclick="' + fn + '(' + (offset - MAX_CHOICES) + ')">Prev</button> ';
    if (data.has_more) nav += '<button class="btn-cancel" onclick="' + fn + '(' + (offset + MAX_CHOICES) + ')">Next</button>';
    nav += '</div>';
    results.innerHTML = html + nav;
    scroll();
}

window.wizSelectCustomer = function(custAccountId, custName) {
    _createWizard.cust_account_id = custAccountId;
    _createWizard.customer_name = custName;
    var results = document.getElementById('wiz-cust-results');
    results.innerHTML = '<p style="color:#6b7280;">Loading ship-to sites...</p>';
    fetch('/api/lookup-customer-sites?cust_account_id=' + custAccountId)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.error) { results.innerHTML = '<p style="color:#991b1b;">Error: ' + escapeHtml(data.error) + '</p>'; return; }
            if (!data.sites || data.sites.length === 0) { results.innerHTML = '<p style="color:#991b1b;">No active ship-to sites found for this customer.</p>'; return; }
            if (data.sites.length === 1) {
                var site = data.sites[0];
                _createWizard.sold_to_org_id = site.sold_to_org_id;
                _createWizard.ship_to_org_id = site.ship_to_org_id;
                results.innerHTML = '<p style="color:#065f46;">Auto-selected site: ' + escapeHtml(site.location) + ' - ' + escapeHtml(site.address) + '</p>';
                setTimeout(function() { wizShowPriceList(); }, 700);
                return;
            }
            var html = '<p style="font-weight:600;margin-bottom:6px;">Select a Ship-To site:</p>';
            html += '<table class="order-table" style="font-size:0.82rem;"><thead><tr><th>#</th><th>Location</th><th>Address</th></tr></thead><tbody>';
            for (var i = 0; i < data.sites.length; i++) {
                var s = data.sites[i];
                html += '<tr style="cursor:pointer;" onclick="wizSelectSite(' + s.sold_to_org_id + ',' + s.ship_to_org_id + ')">';
                html += '<td>' + (i + 1) + '</td><td><b>' + escapeHtml(s.location) + '</b></td><td>' + escapeHtml(s.address) + '</td></tr>';
            }
            html += '</tbody></table>';
            results.innerHTML = html;
            scroll();
        })
        .catch(function(err) { results.innerHTML = '<p style="color:#991b1b;">Network error: ' + escapeHtml(err.message) + '</p>'; });
};

window.wizSelectSite = function(soldToOrgId, shipToOrgId) {
    _createWizard.sold_to_org_id = soldToOrgId;
    _createWizard.ship_to_org_id = shipToOrgId;
    wizShowPriceList();
};

function wizShowPriceList() {
    _createWizard.step = 5;
    var wiz = document.getElementById('create-wizard');
    var html = '<h3>➕ Create New Sales Order</h3>';
    html += '<p style="color:#6b7280;font-size:0.85rem;margin-bottom:12px;">Step 5 of 6: Select Price List and Selling Price</p>';
    html += '<div id="wiz-price-results"><p style="color:#6b7280;">Loading price lists for ' + escapeHtml(_createWizard.ordered_item) + '...</p></div>';
    html += '<div id="wiz-price-form" style="display:none;margin-top:10px;">';
    html += '<div class="form-grid"><div><label>Unit List Price</label><input type="number" id="wiz-list-price" readonly step="0.01"></div><div><label>Selling Price</label><input type="number" id="wiz-sell-price" step="0.01" placeholder="Enter or keep same as list"></div></div>';
    html += '<div class="form-actions"><button class="btn-submit" onclick="wizStep5Next()">Next</button><button class="btn-cancel" onclick="cancelCreateOrder(this)">Cancel</button></div>';
    html += '</div>';
    wiz.innerHTML = html;
    scroll();
    wizLoadPrices(0);
}

function wizLoadPrices(offset) {
    fetch('/api/lookup-prices?item_id=' + _createWizard.inventory_item_id + '&offset=' + offset)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var results = document.getElementById('wiz-price-results');
            if (data.error) { results.innerHTML = '<p style="color:#991b1b;">Error: ' + escapeHtml(data.error) + '</p>'; return; }
            if (!data.prices || data.prices.length === 0) { results.innerHTML = '<p style="color:#991b1b;">No price lists found for this item.</p>'; return; }
            var html = '<table class="order-table" style="font-size:0.82rem;"><thead><tr><th>#</th><th>Price List</th><th>Unit Price</th></tr></thead><tbody>';
            for (var i = 0; i < data.prices.length; i++) {
                var p = data.prices[i];
                html += '<tr style="cursor:pointer;" onclick="wizSelectPrice(' + p.price_list_id + ',' + p.unit_list_price + ')">';
                html += '<td>' + (offset + i + 1) + '</td><td><b>' + escapeHtml(p.price_list_name) + '</b></td><td>$' + Number(p.unit_list_price).toFixed(2) + '</td></tr>';
            }
            html += '</tbody></table>';
            var nav = '<div style="margin-top:8px;">';
            if (offset > 0) nav += '<button class="btn-cancel" onclick="wizLoadPrices(' + (offset - MAX_CHOICES) + ')">Prev</button> ';
            if (data.has_more) nav += '<button class="btn-cancel" onclick="wizLoadPrices(' + (offset + MAX_CHOICES) + ')">Next</button>';
            nav += '</div>';
            results.innerHTML = html + nav;
            scroll();
        })
        .catch(function(err) { document.getElementById('wiz-price-results').innerHTML = '<p style="color:#991b1b;">Network error: ' + escapeHtml(err.message) + '</p>'; });
}

window.wizSelectPrice = function(priceListId, unitPrice) {
    _createWizard.price_list_id = priceListId;
    _createWizard.unit_list_price = Number(unitPrice);
    document.getElementById('wiz-list-price').value = Number(unitPrice).toFixed(2);
    document.getElementById('wiz-sell-price').value = Number(unitPrice).toFixed(2);
    document.getElementById('wiz-price-form').style.display = 'block';
    scroll();
};

window.wizStep5Next = function() {
    var sp = parseFloat(document.getElementById('wiz-sell-price').value);
    if (!sp || sp <= 0) sp = _createWizard.unit_list_price;
    _createWizard.unit_selling_price = sp;
    _createWizard.step = 6;
    wizShowPaymentAndRep();
};

function wizShowPaymentAndRep() {
    var wiz = document.getElementById('create-wizard');
    var html = '<h3>➕ Create New Sales Order</h3>';
    html += '<p style="color:#6b7280;font-size:0.85rem;margin-bottom:12px;">Step 6 of 6: Select Payment Term and Sales Rep</p>';
    html += '<div style="display:flex;gap:16px;flex-wrap:wrap;">';
    html += '<div style="flex:1;min-width:220px;"><h4 style="margin:0 0 6px;">Payment Terms</h4><div id="wiz-terms-results"><p style="color:#6b7280;">Loading...</p></div></div>';
    html += '<div style="flex:1;min-width:220px;"><h4 style="margin:0 0 6px;">Sales Reps</h4><div id="wiz-reps-results"><p style="color:#6b7280;">Loading...</p></div></div>';
    html += '</div>';
    html += '<div id="wiz-final-submit" style="display:none;margin-top:14px;">';
    html += '<div class="card" style="background:#f0fdf4;border-color:#86efac;margin-bottom:12px;">';
    html += '<h4 style="color:#065f46;margin:0 0 8px;">Order Summary</h4><div id="wiz-summary"></div></div>';
    html += '<div class="form-actions"><button class="btn-submit" onclick="wizSubmitOrder()">Submit Order</button><button class="btn-cancel" onclick="cancelCreateOrder(this)">Cancel</button></div>';
    html += '</div>';
    wiz.innerHTML = html;
    scroll();
    wizLoadTerms(0);
    wizLoadReps(0);
}

function wizLoadTerms(offset) {
    _createWizard._termOffset = offset;
    fetch('/api/lookup-payment-terms?offset=' + offset)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var results = document.getElementById('wiz-terms-results');
            if (data.error) { results.innerHTML = '<p style="color:#991b1b;">Error: ' + escapeHtml(data.error) + '</p>'; return; }
            if (!data.terms || data.terms.length === 0) { results.innerHTML = '<p style="color:#991b1b;">No payment terms found.</p>'; return; }
            var html = '<div style="max-height:180px;overflow-y:auto;">';
            for (var i = 0; i < data.terms.length; i++) {
                var t = data.terms[i];
                var sel = (_createWizard.payment_term_id === t.term_id) ? ' style="background:#d1fae5;font-weight:700;"' : ' style="cursor:pointer;"';
                html += '<div' + sel + ' onclick="wizSelectTerm(' + t.term_id + ',\'' + escapeHtml(t.term_name).replace(/'/g, "\\'") + '\')" class="wiz-list-item">';
                html += (offset + i + 1) + '. ' + escapeHtml(t.term_name) + '</div>';
            }
            html += '</div>';
            var nav = '';
            if (offset > 0) nav += '<button class="btn-cancel" style="font-size:0.75rem;padding:3px 8px;" onclick="wizLoadTerms(' + (offset - MAX_CHOICES) + ')">Prev</button> ';
            if (data.has_more) nav += '<button class="btn-cancel" style="font-size:0.75rem;padding:3px 8px;" onclick="wizLoadTerms(' + (offset + MAX_CHOICES) + ')">Next</button>';
            results.innerHTML = html + nav;
            scroll();
        });
}

function wizLoadReps(offset) {
    _createWizard._repOffset = offset;
    fetch('/api/lookup-salesreps?offset=' + offset)
        .then(function(r) { return r.json(); })
        .then(function(data) {
            var results = document.getElementById('wiz-reps-results');
            if (data.error) { results.innerHTML = '<p style="color:#991b1b;">Error: ' + escapeHtml(data.error) + '</p>'; return; }
            if (!data.reps || data.reps.length === 0) { results.innerHTML = '<p style="color:#991b1b;">No sales reps found.</p>'; return; }
            var html = '<div style="max-height:180px;overflow-y:auto;">';
            for (var i = 0; i < data.reps.length; i++) {
                var r = data.reps[i];
                var sel = (_createWizard.salesrep_id === r.salesrep_id) ? ' style="background:#d1fae5;font-weight:700;"' : ' style="cursor:pointer;"';
                html += '<div' + sel + ' onclick="wizSelectRep(' + r.salesrep_id + ',\'' + escapeHtml(r.salesrep_name).replace(/'/g, "\\'") + '\')" class="wiz-list-item">';
                html += (offset + i + 1) + '. ' + escapeHtml(r.salesrep_name) + '</div>';
            }
            html += '</div>';
            var nav = '';
            if (offset > 0) nav += '<button class="btn-cancel" style="font-size:0.75rem;padding:3px 8px;" onclick="wizLoadReps(' + (offset - MAX_CHOICES) + ')">Prev</button> ';
            if (data.has_more) nav += '<button class="btn-cancel" style="font-size:0.75rem;padding:3px 8px;" onclick="wizLoadReps(' + (offset + MAX_CHOICES) + ')">Next</button>';
            results.innerHTML = html + nav;
            scroll();
        });
}

window.wizSelectTerm = function(termId, termName) {
    _createWizard.payment_term_id = termId;
    _createWizard.payment_term_name = termName;
    wizCheckFinalReady();
    wizLoadTerms(_createWizard._termOffset || 0);
};

window.wizSelectRep = function(repId, repName) {
    _createWizard.salesrep_id = repId;
    _createWizard.salesrep_name = repName;
    wizCheckFinalReady();
    wizLoadReps(_createWizard._repOffset || 0);
};

function wizCheckFinalReady() {
    if (_createWizard.payment_term_id && _createWizard.salesrep_id) {
        document.getElementById('wiz-final-submit').style.display = 'block';
        var sum = '<table class="order-table" style="font-size:0.82rem;"><tbody>';
        sum += '<tr><td style="font-weight:600;width:40%;">Customer PO</td><td>' + escapeHtml(_createWizard.cust_po_number) + '</td></tr>';
        sum += '<tr><td style="font-weight:600;">Item</td><td>' + escapeHtml(_createWizard.ordered_item) + ' (ID: ' + _createWizard.inventory_item_id + ')</td></tr>';
        sum += '<tr><td style="font-weight:600;">Quantity</td><td>' + _createWizard.ordered_quantity + '</td></tr>';
        sum += '<tr><td style="font-weight:600;">Customer</td><td>' + escapeHtml(_createWizard.customer_name || '') + '</td></tr>';
        sum += '<tr><td style="font-weight:600;">Ship-To Org ID</td><td>' + _createWizard.ship_to_org_id + '</td></tr>';
        sum += '<tr><td style="font-weight:600;">Sold-To Org ID</td><td>' + _createWizard.sold_to_org_id + '</td></tr>';
        sum += '<tr><td style="font-weight:600;">Price List ID</td><td>' + _createWizard.price_list_id + '</td></tr>';
        sum += '<tr><td style="font-weight:600;">Unit List Price</td><td>$' + Number(_createWizard.unit_list_price).toFixed(2) + '</td></tr>';
        sum += '<tr><td style="font-weight:600;">Selling Price</td><td>$' + Number(_createWizard.unit_selling_price).toFixed(2) + '</td></tr>';
        sum += '<tr><td style="font-weight:600;">Payment Term</td><td>' + escapeHtml(_createWizard.payment_term_name) + '</td></tr>';
        sum += '<tr><td style="font-weight:600;">Sales Rep</td><td>' + escapeHtml(_createWizard.salesrep_name) + '</td></tr>';
        sum += '</tbody></table>';
        document.getElementById('wiz-summary').innerHTML = sum;
        scroll();
    }
}

window.wizSubmitOrder = function() {
    var data = {
        cust_po_number: _createWizard.cust_po_number,
        inventory_item_id: _createWizard.inventory_item_id,
        ordered_item: _createWizard.ordered_item,
        ordered_quantity: _createWizard.ordered_quantity,
        sold_to_org_id: _createWizard.sold_to_org_id,
        ship_to_org_id: _createWizard.ship_to_org_id,
        price_list_id: _createWizard.price_list_id,
        unit_list_price: _createWizard.unit_list_price,
        unit_selling_price: _createWizard.unit_selling_price,
        payment_term_id: _createWizard.payment_term_id,
        salesrep_id: _createWizard.salesrep_id
    };

    var wizMsg = document.getElementById('create-wizard-msg');
    if (wizMsg) wizMsg.remove();

    addBot('Submitting your order, please wait...');
    runOperationWithThinking(
        function() {
            return fetch('/api/create-order', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data)
            }).then(function(r) { return r.json(); });
        },
        {
            thinking: 'validating wizard selections...',
            fetching: 'creating order in erp...',
            preparing: 'preparing order confirmation...'
        }
    )
    .then(function(resp) { handleServerResponse(resp); })
    .catch(function(err) { addBotError('Create order failed: ' + err.message); });
};

window.cancelCreateOrder = function(btn) {
    var formMsg = btn.closest('.message');
    if (formMsg) formMsg.remove();
    addBot('Order creation cancelled.');
};

function addAddLineForm(data) {
    const msg = document.createElement("div");
    msg.className = "message bot";
    msg.innerHTML = `
        <div class="avatar">🤖</div>
        <div class="form-card">
            <h3>Add Line to Order</h3>
            <div class="form-grid">
                <div><label>Header ID</label><input id="al_header" value="${escapeHtml(String(data.header_id || ""))}" type="number" placeholder="Header ID"></div>
                <div><label>Inventory Item ID</label><input id="al_item_id" type="number" placeholder="12027"></div>
                <div><label>Ordered Item</label><input id="al_item" type="text" placeholder="ITEM001"></div>
                <div><label>Quantity</label><input id="al_qty" type="number" step="0.01" min="1" value="1"></div>
                <div><label>Unit List Price</label><input id="al_list" type="number" step="0.01" min="0" value="0"></div>
                <div><label>Unit Selling Price</label><input id="al_sell" type="number" step="0.01" min="0" value="0"></div>
            </div>
            <div class="form-actions">
                <button class="primary" onclick="submitAddLine(this)">Add Line</button>
                <button class="secondary" onclick="removeForm(this)">Cancel</button>
            </div>
        </div>
    `;
    chatMessages.appendChild(msg);
    scroll();
}

function submitAddLine(btn) {
    const root = btn.closest(".form-card");
    const payload = {
        header_id: Number(root.querySelector("#al_header").value),
        inventory_item_id: Number(root.querySelector("#al_item_id").value || 12027),
        ordered_item: root.querySelector("#al_item").value,
        ordered_quantity: Number(root.querySelector("#al_qty").value || 1),
        unit_list_price: Number(root.querySelector("#al_list").value || 0),
        unit_selling_price: Number(root.querySelector("#al_sell").value || 0)
    };

    if (!payload.header_id) {
        addBotError("Header ID is required.");
        return;
    }

    fetch("/api/add-line", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
    })
    .then(r => r.json())
    .then(handleServerResponse)
    .catch(err => addBotError("Add line failed: " + err.message));
}

function addCreateResultCard(result) {
    const msg = document.createElement("div");
    msg.className = "message bot";
    let html = `<div class="avatar">🤖</div><div class="card">`;

    if (result.success) {
        html += `<h3>Operation Successful</h3>`;
    } else if (result.error) {
        html += `<h3>Operation Failed</h3><p style="color:#991b1b;">${escapeHtml(result.error)}</p>`;
    } else {
        html += `<h3>Operation Response</h3>`;
    }

    html += `<table class="tbl"><tbody>`;
    Object.keys(result || {}).forEach(k => {
        if (k === "success") return;
        const v = result[k];
        if (v === null || v === undefined || String(v) === "") return;
        html += `<tr><td style="font-weight:600;width:40%;">${escapeHtml(k)}</td><td>${escapeHtml(String(v))}</td></tr>`;
    });
    html += `</tbody></table></div>`;

    msg.innerHTML = html;
    chatMessages.appendChild(msg);
    scroll();
}

function addEmailForm(data) {
    const msg = document.createElement("div");
    msg.className = "message bot";
    const hasData = !!data.has_data;

    msg.innerHTML = `
        <div class="avatar">🤖</div>
        <div class="form-card">
            <h3>Send Email</h3>
            ${hasData ? "" : "<p style='color:#991b1b;font-size:0.85rem;margin-bottom:8px;'>No operation data available yet. Do an order operation first.</p>"}
            <div class="form-grid">
                <div class="full"><label>To</label><input id="em_to" type="email" value="${escapeHtml(data.to_email || "")}" placeholder="recipient@company.com"></div>
                <div class="full"><label>Subject</label><input id="em_sub" type="text" value="Oracle ERP Order Details Update"></div>
                <div class="full"><label>Message</label><input id="em_body" type="text" value="Please find the requested order details structured below."></div>
                <div class="full"><label>Attachment Format</label>
                    <select id="em_fmt" style="width:100%;padding:9px 10px;border:1px solid var(--border);border-radius:8px;font-size:0.86rem;">
                        <option value="excel">Excel (.xlsx)</option>
                        <option value="csv">CSV (.csv)</option>
                        <option value="json">JSON (.json)</option>
                    </select>
                </div>
            </div>
            <div class="form-actions">
                <button class="primary" onclick="submitEmail(this)" ${hasData ? "" : "disabled"}>Send Email</button>
                <button class="secondary" onclick="removeForm(this)">Cancel</button>
                <button class="secondary" onclick="previewEmail()">Preview</button>
            </div>
            <div id="email_preview" style="margin-top:10px;font-size:0.82rem;"></div>
        </div>
    `;

    chatMessages.appendChild(msg);
    scroll();
}

function previewEmail() {
    fetch("/api/email-preview")
        .then(r => r.json())
        .then(data => {
            const box = document.getElementById("email_preview");
            if (!box) return;
            box.innerHTML = "";
            if (data.html) {
                const iframe = document.createElement("iframe");
                iframe.setAttribute("sandbox", "allow-same-origin");
                iframe.style.cssText = "width:100%;height:400px;border:1px solid #e5e7eb;border-radius:8px;";
                box.appendChild(iframe);
                const iDoc = iframe.contentDocument || iframe.contentWindow.document;
                iDoc.open();
                iDoc.write(data.html);
                iDoc.close();
            } else {
                box.textContent = "No email content available.";
            }
        })
        .catch(err => addBotError("Preview failed: " + err.message));
}
