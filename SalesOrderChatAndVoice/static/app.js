/* ══════════════════════════════════════════════════
   Sales Order Assistant — JavaScript Application
   Voice: uses browser Web Speech API (no server mic needed)
   All fetch calls include credentials for session cookies
   ══════════════════════════════════════════════════ */

// ── State ────────────────────────────────────────
let currentStage = "chat";
let selectedIndex = 0;
let stageRows = [];
let stageContext = {};
let isProcessing = false;

// ── DOM Refs ─────────────────────────────────────
const chatMessages = document.getElementById("chat-messages");
const chatInput = document.getElementById("chat-input");
const stagePanel = document.getElementById("stage-panel");
const fieldsCollected = document.getElementById("fields-collected");
const faqList = document.getElementById("faq-list");

// ── Init ─────────────────────────────────────────
document.addEventListener("DOMContentLoaded", function() {
    chatInput.addEventListener("keydown", function(e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });
    document.getElementById("auto-email-toggle").addEventListener("change", onAutoEmailToggle);
    document.getElementById("auto-email-to").addEventListener("change", function() {
        var enabled = document.getElementById("auto-email-toggle").checked;
        api("/api/auto-email", { enabled: enabled, to: this.value.trim() });
    });
    loadState();
});

// ── API helper (always sends session cookies) ────
function api(endpoint, body) {
    var opts = {
        method: body ? "POST" : "GET",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin"
    };
    if (body) opts.body = JSON.stringify(body);
    return fetch(endpoint, opts).then(function(res) { return res.json(); });
}

// ── Load initial state ───────────────────────────
function loadState() {
    api("/api/state").then(function(data) {
        currentStage = data.stage || "chat";
        renderMessages(data.messages || []);
        renderFields(data.collected || {});
        renderFAQ(data.faq || []);
        if (!data.messages || data.messages.length === 0) {
            addMessageDOM("assistant", "👋 Welcome to the Centroid Sales Order Assistant!\n\nYou can create orders, look up existing ones, search by date/status, or get order details by customer. Type your request or use the FAQ in the sidebar.");
        }
        if (data.auto_email_enabled) {
            document.getElementById("auto-email-toggle").checked = true;
            document.getElementById("auto-email-config").classList.remove("hidden");
            if (data.auto_email_to) {
                document.getElementById("auto-email-to").value = data.auto_email_to;
            }
        }
    });
}

// ── Render messages ──────────────────────────────
function renderMessages(messages) {
    chatMessages.innerHTML = "";
    for (var i = 0; i < messages.length; i++) {
        addMessageDOM(messages[i].role, messages[i].content);
    }
    scrollToBottom();
}

function addMessageDOM(role, content) {
    var div = document.createElement("div");
    div.className = "message " + role;
    var bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.innerHTML = formatMarkdown(content);
    div.appendChild(bubble);
    chatMessages.appendChild(div);
}

function scrollToBottom() {
    var container = document.getElementById("chat-container");
    setTimeout(function() { container.scrollTop = container.scrollHeight; }, 80);
}

function formatMarkdown(text) {
    if (!text) return "";
    text = text.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
    text = text.replace(/`([^`]+)`/g, "<code>$1</code>");
    text = text.replace(/\n/g, "<br>");
    return text;
}

// ── Send chat message ────────────────────────────
function sendMessage() {
    var msg = chatInput.value.trim();
    if (!msg || isProcessing) return;

    chatInput.value = "";
    addMessageDOM("user", msg);
    hideStagePanel();
    showLoading();
    isProcessing = true;

    api("/api/chat", { message: msg }).then(function(data) {
        hideLoading();
        isProcessing = false;

        if (data.messages) renderMessages(data.messages);
        if (data.collected) renderFields(data.collected);

        currentStage = data.stage || "chat";
        handleStageResponse(data);
    }).catch(function(err) {
        hideLoading();
        isProcessing = false;
        addMessageDOM("assistant", "❌ Connection error. Please try again.");
    });
}

// ── Handle stage transitions ─────────────────────
function handleStageResponse(data) {
    hideStagePanel();

    var stage = data.stage;
    if (stage === "chat") {
        enableInput(true);
    } else if (stage === "select_item" || stage === "select_price" || stage === "select_term" ||
               stage === "select_rep" || stage === "select_line_type" || stage === "select_customer" ||
               stage === "select_customer_by_item" || stage === "select_site") {
        showSelectionUI(data);
        enableInput(false);
    } else if (stage === "selling_price_override") {
        showSellingPriceUI(data);
        enableInput(false);
    } else if (stage === "confirm_order") {
        showConfirmOrderUI(data);
        enableInput(false);
    } else if (stage === "done" || stage === "show_get_order") {
        showOrderResultUI(data);
        enableInput(false);
    } else if (stage === "show_advanced_search") {
        showAdvancedSearchUI(data);
        enableInput(false);
    } else if (stage === "order_details_by_customer") {
        showOrderDetailsUI(data);
        enableInput(false);
    } else if (stage === "send_email_flow") {
        showEmailUI(data);
        enableInput(false);
    } else if (stage === "error") {
        showErrorUI();
        enableInput(false);
    } else {
        enableInput(true);
    }
}

// ══════════════════════════════════════════════════
// Selection UI (items, prices, terms, reps, customers, sites)
// ══════════════════════════════════════════════════
function showSelectionUI(data) {
    var rows = data.rows || [];
    stageRows = rows;
    selectedIndex = 0;
    stageContext = data;

    var labels = {
        select_item: "Inventory Item", select_price: "Price List", select_term: "Payment Term",
        select_rep: "Sales Representative", select_line_type: "Line Type",
        select_customer: "Customer", select_customer_by_item: "Customer", select_site: "Customer Site"
    };
    var label = labels[data.stage] || "Option";
    var html = '<h3>🔍 Select ' + label + '</h3>';

    if (data.stage === "select_customer") {
        html += '<div class="mb-3" style="display:flex;gap:8px;">' +
            '<input type="text" id="customer-search" class="input-field" style="margin:0;flex:1;" placeholder="Search customer by name...">' +
            '<button class="btn btn-primary" onclick="searchCustomer()">🔍 Search</button></div>';
    }

    if (rows.length === 0) {
        html += '<div class="warning-banner">No ' + label.toLowerCase() + ' records found.</div>';
    } else {
        html += '<div class="selection-list">';
        for (var i = 0; i < rows.length; i++) {
            var display = formatRowDisplay(data.stage, rows[i], i);
            html += '<div class="selection-item ' + (i === 0 ? 'selected' : '') + '" onclick="selectItem(' + i + ')" data-idx="' + i + '">' +
                '<input type="radio" name="selection" ' + (i === 0 ? 'checked' : '') + '>' +
                '<span>' + display + '</span></div>';
        }
        html += '</div>';
    }

    html += '<div class="btn-group">';
    if (rows.length > 0) {
        html += '<button class="btn btn-success" onclick="confirmSelection()">✅ Confirm ' + label + '</button>';
    }
    html += '<button class="btn" onclick="fetchNextRows(\'next\')">📑 Next Page</button>';
    html += '<button class="btn" onclick="fetchNextRows(\'prev\')">⬅️ Previous</button>';
    html += '<button class="btn btn-danger" onclick="backToChat()">🏠 Back to Chat</button>';
    html += '</div>';

    stagePanel.innerHTML = html;
    stagePanel.classList.remove("hidden");
    scrollToBottom();
}

function formatRowDisplay(stage, row, idx) {
    var n = idx + 1;
    if (stage === "select_item") {
        return '<strong>[' + n + ']</strong> ID=' + row.inventory_item_id + '&nbsp;&nbsp;' + row.segment1 + '&nbsp;&nbsp;' + (row.description || '');
    } else if (stage === "select_price") {
        return '<strong>[' + n + ']</strong> ' + row.price_list_name + '&nbsp;&nbsp;$' + Number(row.unit_list_price).toFixed(2);
    } else if (stage === "select_term") {
        return '<strong>[' + n + ']</strong> ID=' + row.term_id + '&nbsp;&nbsp;' + row.term_name;
    } else if (stage === "select_rep") {
        return '<strong>[' + n + ']</strong> ID=' + row.salesrep_id + '&nbsp;&nbsp;' + row.salesrep_name;
    } else if (stage === "select_line_type") {
        return '<strong>[' + n + ']</strong> ' + row.line_type_name + ' (ID: ' + row.line_type_id + ')';
    } else if (stage === "select_customer" || stage === "select_customer_by_item") {
        return '<strong>[' + n + ']</strong> ' + row.customer_name + '&nbsp;&nbsp;(Acct#: ' + row.account_number + ', ID: ' + row.cust_account_id + ')';
    } else if (stage === "select_site") {
        return '<strong>[' + n + ']</strong> ' + row.customer_name + '&nbsp;&nbsp;[' + (row.location || '') + '] ' + (row.address || '') + ' (Ship-To: ' + row.ship_to_org_id + ')';
    }
    return '<strong>[' + n + ']</strong> ' + JSON.stringify(row).substring(0, 100);
}

function selectItem(idx) {
    selectedIndex = idx;
    var items = document.querySelectorAll(".selection-item");
    for (var i = 0; i < items.length; i++) {
        if (i === idx) {
            items[i].classList.add("selected");
            items[i].querySelector("input[type=radio]").checked = true;
        } else {
            items[i].classList.remove("selected");
            items[i].querySelector("input[type=radio]").checked = false;
        }
    }
}

function confirmSelection() {
    showLoading();
    api("/api/select", { stage: currentStage, index: selectedIndex }).then(function(data) {
        hideLoading();
        if (data.error) {
            addMessageDOM("assistant", "❌ " + data.error);
            return;
        }
        if (data.messages) renderMessages(data.messages);
        if (data.collected) renderFields(data.collected);
        currentStage = data.stage || "chat";
        handleStageResponse(data);
    }).catch(function() { hideLoading(); });
}

function fetchNextRows(direction) {
    showLoading();
    api("/api/fetch-next", { stage: currentStage, direction: direction }).then(function(data) {
        hideLoading();
        if (data.rows) {
            stageRows = data.rows;
            var fakeResponse = {};
            for (var k in stageContext) fakeResponse[k] = stageContext[k];
            fakeResponse.rows = data.rows;
            fakeResponse.stage = currentStage;
            showSelectionUI(fakeResponse);
        }
    }).catch(function() { hideLoading(); });
}

function searchCustomer() {
    var el = document.getElementById("customer-search");
    var name = el ? el.value : "";
    if (!name.trim()) return;
    showLoading();
    api("/api/search-customer", { name: name }).then(function(data) {
        hideLoading();
        currentStage = data.stage || "select_customer";
        showSelectionUI({ stage: currentStage, rows: data.rows || [] });
    }).catch(function() { hideLoading(); });
}

// ══════════════════════════════════════════════════
// Selling Price Override UI
// ══════════════════════════════════════════════════
function showSellingPriceUI(data) {
    var unitPrice = data.unit_list_price || 0;
    var html = '<h3>💰 Selling Price</h3>' +
        '<p class="text-sm mb-2">Unit List Price: <strong>$' + Number(unitPrice).toFixed(2) + '</strong></p>' +
        '<p class="text-sm mb-2">Enter a custom selling price, or leave blank to use the list price:</p>' +
        '<input type="text" id="selling-price-input" class="input-field" placeholder="Leave blank for list price">' +
        '<div class="btn-group">' +
        '<button class="btn btn-success" onclick="confirmSellingPrice()">✅ Confirm Selling Price</button>' +
        '<button class="btn btn-danger" onclick="backToChat()">🏠 Back to Chat</button></div>';
    stagePanel.innerHTML = html;
    stagePanel.classList.remove("hidden");
    scrollToBottom();
}

function confirmSellingPrice() {
    var el = document.getElementById("selling-price-input");
    var sp = el ? el.value : "";
    showLoading();
    api("/api/selling-price", { selling_price: sp }).then(function(data) {
        hideLoading();
        if (data.messages) renderMessages(data.messages);
        if (data.collected) renderFields(data.collected);
        currentStage = data.stage || "chat";
        handleStageResponse(data);
    }).catch(function() { hideLoading(); });
}

// ══════════════════════════════════════════════════
// Confirm Order UI
// ══════════════════════════════════════════════════
function showConfirmOrderUI(data) {
    var collected = data.collected || {};
    var html = '<h3>📋 Order Summary — Review Before Submitting</h3>';
    html += '<table class="summary-table">';
    var keys = Object.keys(collected);
    for (var i = 0; i < keys.length; i++) {
        var key = keys[i];
        var val = collected[key];
        if (val !== null && val !== undefined && !key.endsWith("_name")) {
            html += '<tr><th>' + key + '</th><td>' + val + '</td></tr>';
        }
    }
    html += '</table>';
    html += '<div class="btn-group">' +
        '<button class="btn btn-success" onclick="submitOrder()">✅ Submit Order</button>' +
        '<button class="btn btn-danger" onclick="backToChat()">🏠 Back to Chat</button></div>';
    stagePanel.innerHTML = html;
    stagePanel.classList.remove("hidden");
    scrollToBottom();
}

function submitOrder() {
    showLoading();
    api("/api/confirm-order", {}).then(function(data) {
        hideLoading();
        if (data.messages) renderMessages(data.messages);
        currentStage = data.stage || "chat";
        handleStageResponse(data);
    }).catch(function() { hideLoading(); });
}

// ══════════════════════════════════════════════════
// Order Result UI (done, show_get_order)
// ══════════════════════════════════════════════════
function showOrderResultUI(data) {
    var orderData = data.order_data || {};
    var status = String(orderData.status || "").toUpperCase();
    var bannerClass = "info", emoji = "ℹ️", label = status;
    if (status === "S") { bannerClass = "success"; emoji = "✅"; label = "Success"; }
    else if (status === "E") { bannerClass = "error"; emoji = "❌"; label = "Error"; }
    else if (status === "W") { bannerClass = "warning"; emoji = "⚠️"; label = "Warning"; }

    var hd = orderData.header_details || {};
    var lines = orderData.lines || [];

    var html = '<div class="erp-banner ' + bannerClass + '">' + emoji + ' <strong>Order ' + label + '!</strong> &nbsp;|&nbsp; Order # ' + (hd["Order Number"] || "N/A") + ' &nbsp;|&nbsp; Header ID ' + (hd["Header ID"] || "N/A") + '</div>';

    if (orderData.message && orderData.message !== "N/A") {
        html += '<div class="warning-banner">💬 ' + escapeHtml(orderData.message) + '</div>';
    }

    // Header Details
    html += '<h3 class="mt-3">🧾 Header Details</h3><table class="summary-table">';
    var hdKeys = Object.keys(hd);
    for (var i = 0; i < hdKeys.length; i++) {
        if (hd[hdKeys[i]] && hd[hdKeys[i]] !== "N/A") {
            html += '<tr><th>' + hdKeys[i] + '</th><td>' + hd[hdKeys[i]] + '</td></tr>';
        }
    }
    html += '</table>';

    // Line Details
    if (lines.length > 0) {
        var cols = ["Line #", "Item", "Qty Ordered", "UOM", "Unit List Price", "Unit Selling Price", "Flow Status"];
        html += '<h3 class="mt-3">📦 Line Details (' + lines.length + ' line' + (lines.length !== 1 ? 's' : '') + ')</h3>';
        html += '<div class="data-table-wrapper"><table class="data-table"><tr>';
        for (var ci = 0; ci < cols.length; ci++) html += '<th>' + cols[ci] + '</th>';
        html += '</tr>';
        for (var li = 0; li < lines.length; li++) {
            html += '<tr>';
            for (var ci2 = 0; ci2 < cols.length; ci2++) html += '<td>' + (lines[li][cols[ci2]] || 'N/A') + '</td>';
            html += '</tr>';
        }
        html += '</table></div>';
    }

    // Buttons
    var headerId = data.header_id || hd["Header ID"];
    html += '<div class="btn-group mt-3">';
    if (headerId && headerId !== "N/A") {
        html += '<button class="btn btn-primary" onclick="startAddLine()">➕ Add a Line</button>';
    }
    html += '<button class="btn" onclick="emailResults()">📧 Send Email</button>';
    html += '<button class="btn btn-danger" onclick="backToChat()">🏠 Back to Chat</button></div>';

    // Raw JSON
    if (data.api_result) {
        html += '<div class="mt-3"><div class="collapsible-header" onclick="toggleCollapsible(this)">🔍 View Full Raw API Response ▶</div>' +
            '<div class="collapsible-body"><div class="json-viewer">' + escapeHtml(JSON.stringify(data.api_result, null, 2)) + '</div></div></div>';
    }

    stagePanel.innerHTML = html;
    stagePanel.classList.remove("hidden");
    scrollToBottom();
}

// ══════════════════════════════════════════════════
// Advanced Search Results UI
// ══════════════════════════════════════════════════
function showAdvancedSearchUI(data) {
    var results = data.search_results || {};
    var rows = results.rows || [];
    var total = results.total_count || 0;
    var columns = results.columns || ["Order Number", "Status", "Creation Date"];

    var html = '<h3>🔍 Advanced Order Search Results</h3>';
    html += '<div class="metrics-bar">' +
        '<div class="metric-card"><div class="metric-label">Total Orders</div><div class="metric-value">' + total + '</div></div>' +
        '<div class="metric-card"><div class="metric-label">Showing</div><div class="metric-value">' + rows.length + '</div></div></div>';

    if (rows.length > 0) {
        html += buildDataTable(columns, rows);
        html += '<div class="mt-2"><button class="download-btn" onclick="downloadSearchCSV()">⬇️ Download CSV</button></div>';
    } else {
        html += '<div class="info-banner">No rows to display.</div>';
    }

    html += '<div class="btn-group mt-3">' +
        '<button class="btn" onclick="emailResults()">📧 Email Results</button>' +
        '<button class="btn btn-danger" onclick="backToChat()">🏠 Back to Chat</button></div>';

    stagePanel.innerHTML = html;
    stagePanel.classList.remove("hidden");
    stageContext.csvRows = rows;
    stageContext.csvColumns = columns;
    scrollToBottom();
}

// ══════════════════════════════════════════════════
// Order Details by Customer UI
// ══════════════════════════════════════════════════
function showOrderDetailsUI(data) {
    var cname = data.customer_name || "";
    var html = '<h3>🔎 Order Details by Customer</h3>' +
        '<div class="info-banner">Enter a customer name (exact match, as stored in Oracle HZ_PARTIES) to retrieve all order lines.</div>' +
        '<label class="form-label">Customer Name:</label>' +
        '<input type="text" id="od-customer-name" class="input-field" value="' + escapeHtml(cname) + '" placeholder="e.g. ACME CORPORATION">' +
        '<div class="btn-group">' +
        '<button class="btn btn-primary" onclick="fetchOrderDetails()">🔍 Fetch Order Details</button>' +
        '<button class="btn btn-danger" onclick="backToChat()">🏠 Back to Chat</button></div>' +
        '<div id="od-results"></div>';
    stagePanel.innerHTML = html;
    stagePanel.classList.remove("hidden");
    // Allow Enter key to trigger search
    setTimeout(function() {
        var inp = document.getElementById("od-customer-name");
        if (inp) inp.addEventListener("keydown", function(e) { if (e.key === "Enter") fetchOrderDetails(); });
    }, 100);
    scrollToBottom();
}

function fetchOrderDetails() {
    var el = document.getElementById("od-customer-name");
    var cname = el ? el.value.trim() : "";
    if (!cname) {
        document.getElementById("od-results").innerHTML = '<div class="error-banner mt-2">Please enter a customer name.</div>';
        return;
    }
    showLoading();
    api("/api/order-details", { customer_name: cname }).then(function(data) {
        hideLoading();
        if (data.messages) renderMessages(data.messages);
        var resultsDiv = document.getElementById("od-results");
        if (!resultsDiv) return;

        if (!data.ok) {
            resultsDiv.innerHTML = '<div class="error-banner mt-2">' + (data.error || 'Error') + '</div>';
            return;
        }

        var rows = data.rows || [];
        var cols = data.columns || [];
        var total = data.total || 0;

        if (rows.length === 0) {
            resultsDiv.innerHTML = '<div class="info-banner mt-2">No orders found for \'' + escapeHtml(cname) + '\'.</div>';
            return;
        }

        var html = '<h3 class="mt-3">📦 Results for: ' + escapeHtml(cname) + '</h3>';
        html += '<div class="metrics-bar"><div class="metric-card"><div class="metric-label">Total Lines</div><div class="metric-value">' + total + '</div></div></div>';
        html += buildDataTableFromDicts(cols, rows);
        html += '<div class="btn-group mt-2">' +
            '<button class="download-btn" onclick="downloadCustomerCSV()">⬇️ Download CSV</button>' +
            '<button class="btn" onclick="emailResults()">📧 Send Email</button></div>';

        resultsDiv.innerHTML = html;
        stageContext.csvDictRows = rows;
        stageContext.csvDictColumns = cols;
        scrollToBottom();
    }).catch(function() {
        hideLoading();
        var rd = document.getElementById("od-results");
        if (rd) rd.innerHTML = '<div class="error-banner mt-2">Connection error.</div>';
    });
}

// ══════════════════════════════════════════════════
// Email UI
// ══════════════════════════════════════════════════
function showEmailUI(data) {
    var collected = data.collected || {};
    var email = collected.email_address || "";
    var html = '<h3>📧 Send Email</h3>' +
        '<div class="info-banner">The order data from your last operation has been attached as a formatted table.</div>' +
        '<label class="form-label">To:</label>' +
        '<input type="email" id="email-to" class="input-field" value="' + escapeHtml(email) + '" placeholder="recipient@domain.com">' +
        '<label class="form-label">Subject:</label>' +
        '<input type="text" id="email-subject" class="input-field" value="Oracle ERP Order Details Update">' +
        '<label class="form-label">Message Body:</label>' +
        '<textarea id="email-body" class="textarea-field">Please find the requested order details structured below.</textarea>' +
        '<div class="btn-group">' +
        '<button class="btn btn-success" onclick="sendEmail()">✅ Send Email</button>' +
        '<button class="btn btn-danger" onclick="backToChat()">🏠 Back to Chat</button></div>' +
        '<div id="email-status"></div>';
    stagePanel.innerHTML = html;
    stagePanel.classList.remove("hidden");
    scrollToBottom();
}

function sendEmail() {
    var toEl = document.getElementById("email-to");
    var subjEl = document.getElementById("email-subject");
    var bodyEl = document.getElementById("email-body");
    var statusDiv = document.getElementById("email-status");
    var to = toEl ? toEl.value.trim() : "";
    var subject = subjEl ? subjEl.value.trim() : "";
    var body = bodyEl ? bodyEl.value.trim() : "";

    if (!to) {
        statusDiv.innerHTML = '<div class="error-banner mt-2">Email address is required.</div>';
        return;
    }

    showLoading();
    api("/api/send-email", { to: to, subject: subject, body: body }).then(function(data) {
        hideLoading();
        if (data.ok) {
            statusDiv.innerHTML = '<div class="success-banner mt-2">✅ ' + (data.response || 'Email sent!') + '</div>';
            if (data.messages) renderMessages(data.messages);
            setTimeout(function() {
                hideStagePanel();
                enableInput(true);
                currentStage = "chat";
            }, 2000);
        } else {
            statusDiv.innerHTML = '<div class="error-banner mt-2">❌ ' + (data.error || 'Failed to send.') + '</div>';
        }
    }).catch(function() {
        hideLoading();
        statusDiv.innerHTML = '<div class="error-banner mt-2">Connection error.</div>';
    });
}

function emailResults() {
    currentStage = "send_email_flow";
    showEmailUI({ collected: {} });
}

// ══════════════════════════════════════════════════
// Error UI
// ══════════════════════════════════════════════════
function showErrorUI() {
    stagePanel.innerHTML = '<div class="error-banner">An error occurred during the operation.</div>' +
        '<div class="btn-group"><button class="btn btn-danger" onclick="backToChat()">🏠 Back to Chat</button></div>';
    stagePanel.classList.remove("hidden");
}

// ══════════════════════════════════════════════════
// Add Line Flow
// ══════════════════════════════════════════════════
function startAddLine() {
    showLoading();
    api("/api/add-line", { action: "start" }).then(function() {
        hideLoading();
        showAddLineItemSearch();
    }).catch(function() { hideLoading(); });
}

function showAddLineItemSearch() {
    var html = '<h3>➕ Add Line — Search Item</h3>' +
        '<div style="display:flex;gap:8px;">' +
        '<input type="text" id="al-item-search" class="input-field" style="margin:0;flex:1;" placeholder="Enter item name/prefix...">' +
        '<button class="btn btn-primary" onclick="addLineSearchItems()">🔍 Search</button></div>' +
        '<div id="al-item-results"></div>' +
        '<div class="btn-group mt-2"><button class="btn btn-danger" onclick="backToChat()">❌ Cancel</button></div>';
    stagePanel.innerHTML = html;
    stagePanel.classList.remove("hidden");
    setTimeout(function() {
        var inp = document.getElementById("al-item-search");
        if (inp) inp.addEventListener("keydown", function(e) { if (e.key === "Enter") addLineSearchItems(); });
    }, 100);
    scrollToBottom();
}

function addLineSearchItems() {
    var el = document.getElementById("al-item-search");
    var query = el ? el.value : "";
    showLoading();
    api("/api/add-line", { action: "search_items", query: query }).then(function(data) {
        hideLoading();
        var rows = data.rows || [];
        stageRows = rows;
        selectedIndex = 0;
        var html = "";
        if (rows.length > 0) {
            html += '<div class="selection-list mt-2">';
            for (var i = 0; i < rows.length; i++) {
                html += '<div class="selection-item ' + (i === 0 ? 'selected' : '') + '" onclick="selectItem(' + i + ')" data-idx="' + i + '">' +
                    '<input type="radio" name="al-item" ' + (i === 0 ? 'checked' : '') + '>' +
                    '<span><strong>[' + (i + 1) + ']</strong> ' + rows[i].segment1 + '&nbsp;&nbsp;' + (rows[i].description || '') + '</span></div>';
            }
            html += '</div><button class="btn btn-success mt-2" onclick="addLineSelectItem()">✅ Confirm Item</button>';
        } else {
            html = '<div class="warning-banner mt-2">No items found.</div>';
        }
        document.getElementById("al-item-results").innerHTML = html;
    }).catch(function() { hideLoading(); });
}

function addLineSelectItem() {
    showLoading();
    api("/api/add-line", { action: "select_item", index: selectedIndex }).then(function(data) {
        hideLoading();
        if (data.ok) showAddLineQtyUI(data.ordered_item);
    }).catch(function() { hideLoading(); });
}

function showAddLineQtyUI(itemName) {
    var html = '<h3>➕ Add Line — Quantity</h3>' +
        '<p class="text-sm mb-2">Item: <strong>' + escapeHtml(itemName) + '</strong></p>' +
        '<input type="text" id="al-qty" class="input-field" placeholder="Enter quantity">' +
        '<div class="btn-group">' +
        '<button class="btn btn-success" onclick="addLineSetQty()">✅ Confirm Quantity</button>' +
        '<button class="btn btn-danger" onclick="backToChat()">❌ Cancel</button></div>';
    stagePanel.innerHTML = html;
    stagePanel.classList.remove("hidden");
    setTimeout(function() {
        var inp = document.getElementById("al-qty");
        if (inp) inp.addEventListener("keydown", function(e) { if (e.key === "Enter") addLineSetQty(); });
    }, 100);
}

function addLineSetQty() {
    var el = document.getElementById("al-qty");
    var qty = el ? el.value : "";
    showLoading();
    api("/api/add-line", { action: "set_qty", quantity: qty }).then(function(data) {
        hideLoading();
        if (data.error) { alert(data.error); return; }
        if (data.ok) showAddLinePriceUI(data.rows || []);
    }).catch(function() { hideLoading(); });
}

function showAddLinePriceUI(rows) {
    stageRows = rows;
    selectedIndex = 0;
    var html = '<h3>➕ Add Line — Select Price List</h3>';
    if (rows.length > 0) {
        html += '<div class="selection-list">';
        for (var i = 0; i < rows.length; i++) {
            html += '<div class="selection-item ' + (i === 0 ? 'selected' : '') + '" onclick="selectItem(' + i + ')" data-idx="' + i + '">' +
                '<input type="radio" name="al-price" ' + (i === 0 ? 'checked' : '') + '>' +
                '<span><strong>[' + (i + 1) + ']</strong> ' + rows[i].price_list_name + '&nbsp;&nbsp;$' + Number(rows[i].unit_list_price).toFixed(2) + '</span></div>';
        }
        html += '</div><button class="btn btn-success mt-2" onclick="addLineSelectPrice()">✅ Confirm Price</button>';
    } else {
        html += '<div class="warning-banner">No price lists found.</div>';
    }
    html += '<div class="btn-group mt-2"><button class="btn btn-danger" onclick="backToChat()">❌ Cancel</button></div>';
    stagePanel.innerHTML = html;
    stagePanel.classList.remove("hidden");
}

function addLineSelectPrice() {
    showLoading();
    api("/api/add-line", { action: "select_price", index: selectedIndex }).then(function(data) {
        hideLoading();
        if (data.ok) showAddLineSellingPriceUI(data.unit_list_price);
    }).catch(function() { hideLoading(); });
}

function showAddLineSellingPriceUI(unitPrice) {
    var html = '<h3>➕ Add Line — Selling Price</h3>' +
        '<p class="text-sm mb-2">Unit List Price: <strong>$' + Number(unitPrice).toFixed(2) + '</strong></p>' +
        '<input type="text" id="al-sp" class="input-field" placeholder="Leave blank for list price">' +
        '<div class="btn-group">' +
        '<button class="btn btn-success" onclick="addLineSetSellingPrice()">✅ Confirm</button>' +
        '<button class="btn btn-danger" onclick="backToChat()">❌ Cancel</button></div>';
    stagePanel.innerHTML = html;
    stagePanel.classList.remove("hidden");
}

function addLineSetSellingPrice() {
    var el = document.getElementById("al-sp");
    var sp = el ? el.value : "";
    showLoading();
    api("/api/add-line", { action: "set_selling_price", selling_price: sp }).then(function(data) {
        hideLoading();
        if (data.ok) showAddLineTermUI(data.rows || []);
    }).catch(function() { hideLoading(); });
}

function showAddLineTermUI(rows) {
    stageRows = rows;
    selectedIndex = 0;
    var html = '<h3>➕ Add Line — Payment Term</h3>';
    if (rows.length > 0) {
        html += '<div class="selection-list">';
        for (var i = 0; i < rows.length; i++) {
            html += '<div class="selection-item ' + (i === 0 ? 'selected' : '') + '" onclick="selectItem(' + i + ')" data-idx="' + i + '">' +
                '<input type="radio" name="al-term" ' + (i === 0 ? 'checked' : '') + '>' +
                '<span><strong>[' + (i + 1) + ']</strong> ' + rows[i].term_name + '</span></div>';
        }
        html += '</div><button class="btn btn-success mt-2" onclick="addLineSelectTerm()">✅ Confirm Term</button>';
    }
    html += '<div class="btn-group mt-2"><button class="btn btn-danger" onclick="backToChat()">❌ Cancel</button></div>';
    stagePanel.innerHTML = html;
    stagePanel.classList.remove("hidden");
}

function addLineSelectTerm() {
    showLoading();
    api("/api/add-line", { action: "select_term", index: selectedIndex }).then(function(data) {
        hideLoading();
        if (data.ok && data.sub_stage === "add_line_submit") {
            showAddLineSubmitUI(data.add_line_data);
        }
    }).catch(function() { hideLoading(); });
}

function showAddLineSubmitUI(ald) {
    var html = '<h3>➕ New Line Summary</h3>' +
        '<table class="summary-table">' +
        '<tr><th>Item</th><td>' + (ald.ordered_item || 'N/A') + '</td></tr>' +
        '<tr><th>Quantity</th><td>' + (ald.quantity || 'N/A') + '</td></tr>' +
        '<tr><th>Unit List Price</th><td>$' + Number(ald.unit_list_price || 0).toFixed(2) + '</td></tr>' +
        '<tr><th>Selling Price</th><td>$' + Number(ald.unit_selling_price || 0).toFixed(2) + '</td></tr>' +
        '<tr><th>Payment Term ID</th><td>' + (ald.payment_term_id || 'N/A') + '</td></tr>' +
        '</table>' +
        '<div class="btn-group">' +
        '<button class="btn btn-success" onclick="addLineSubmit()">✅ Submit Line</button>' +
        '<button class="btn btn-danger" onclick="backToChat()">❌ Cancel</button></div>';
    stagePanel.innerHTML = html;
    stagePanel.classList.remove("hidden");
}

function addLineSubmit() {
    showLoading();
    api("/api/add-line", { action: "submit" }).then(function(data) {
        hideLoading();
        if (data.messages) renderMessages(data.messages);
        if (data.ok) {
            currentStage = data.stage || "done";
            handleStageResponse(data);
        } else {
            stagePanel.innerHTML = '<div class="error-banner">' + (data.error || 'Failed to add line.') + '</div>' +
                '<div class="btn-group"><button class="btn btn-danger" onclick="backToChat()">🏠 Back to Chat</button></div>';
        }
    }).catch(function() { hideLoading(); });
}

// ══════════════════════════════════════════════════
// Voice Input — Browser Web Speech API
// ══════════════════════════════════════════════════
function voiceInput() {
    var micBtn = document.getElementById("btn-mic");

    // Check browser support
    var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        // Fallback: try server-side voice
        serverVoiceInput();
        return;
    }

    var recognition = new SpeechRecognition();
    recognition.lang = "en-US";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    recognition.continuous = false;

    micBtn.textContent = "🔴";
    micBtn.disabled = true;
    addMessageDOM("assistant", "🎙️ Listening... speak now.");
    scrollToBottom();

    recognition.onresult = function(event) {
        var transcript = event.results[0][0].transcript;
        micBtn.textContent = "🎙️";
        micBtn.disabled = false;
        // Remove the listening message
        removeLastAssistantMessage();
        if (transcript && transcript.trim()) {
            chatInput.value = transcript.trim();
            sendMessage();
        }
    };

    recognition.onerror = function(event) {
        micBtn.textContent = "🎙️";
        micBtn.disabled = false;
        removeLastAssistantMessage();
        if (event.error === "no-speech") {
            addMessageDOM("assistant", "🎙️ Nothing heard — try speaking louder.");
        } else if (event.error === "not-allowed") {
            addMessageDOM("assistant", "⚠️ Microphone access denied. Please allow microphone access in your browser settings.");
        } else {
            addMessageDOM("assistant", "⚠️ Voice error: " + event.error + ". Try again or type your request.");
        }
        scrollToBottom();
    };

    recognition.onend = function() {
        micBtn.textContent = "🎙️";
        micBtn.disabled = false;
    };

    try {
        recognition.start();
    } catch (e) {
        micBtn.textContent = "🎙️";
        micBtn.disabled = false;
        addMessageDOM("assistant", "⚠️ Could not start voice recognition. Please type your request.");
    }
}

function serverVoiceInput() {
    var micBtn = document.getElementById("btn-mic");
    micBtn.textContent = "🔴";
    micBtn.disabled = true;
    addMessageDOM("assistant", "🎙️ Listening on server... speak now.");
    scrollToBottom();

    api("/api/voice", {}).then(function(data) {
        micBtn.textContent = "🎙️";
        micBtn.disabled = false;
        removeLastAssistantMessage();
        if (data.text) {
            chatInput.value = data.text;
            sendMessage();
        } else if (data.error) {
            addMessageDOM("assistant", "⚠️ " + data.error);
            scrollToBottom();
        }
    }).catch(function() {
        micBtn.textContent = "🎙️";
        micBtn.disabled = false;
        removeLastAssistantMessage();
        addMessageDOM("assistant", "⚠️ Voice input failed. Please type your request.");
        scrollToBottom();
    });
}

function removeLastAssistantMessage() {
    var msgs = chatMessages.querySelectorAll(".message.assistant");
    if (msgs.length > 0) {
        var last = msgs[msgs.length - 1];
        var text = last.textContent || "";
        if (text.indexOf("Listening") !== -1) {
            last.remove();
        }
    }
}

// ══════════════════════════════════════════════════
// Sidebar & Utility
// ══════════════════════════════════════════════════
function renderFields(collected) {
    if (!collected) {
        fieldsCollected.innerHTML = '<p class="empty-state">No fields collected yet.</p>';
        return;
    }
    var hasAny = false;
    var html = "";
    var keys = Object.keys(collected);
    for (var i = 0; i < keys.length; i++) {
        if (collected[keys[i]] !== null && collected[keys[i]] !== undefined) {
            hasAny = true;
            html += '<div class="field-item"><span class="field-key">' + keys[i] + '</span><span class="field-val">' + collected[keys[i]] + '</span></div>';
        }
    }
    fieldsCollected.innerHTML = hasAny ? html : '<p class="empty-state">No fields collected yet.</p>';
}

function renderFAQ(questions) {
    var html = "";
    for (var i = 0; i < questions.length; i++) {
        html += '<button class="faq-btn" onclick="askFAQ(this.getAttribute(\'data-q\'))" data-q="' + escapeHtml(questions[i]) + '">' + questions[i] + '</button>';
    }
    faqList.innerHTML = html;
}

function askFAQ(question) {
    showLoading();
    api("/api/faq", { question: question }).then(function(data) {
        hideLoading();
        if (data.messages) renderMessages(data.messages);
    }).catch(function() { hideLoading(); });
}

function backToChat() {
    showLoading();
    api("/api/back", {}).then(function() {
        hideLoading();
        hideStagePanel();
        enableInput(true);
        currentStage = "chat";
        loadState();
    }).catch(function() {
        hideLoading();
        hideStagePanel();
        enableInput(true);
        currentStage = "chat";
    });
}

function clearChat() {
    api("/api/clear", {}).then(function() {
        chatMessages.innerHTML = "";
        hideStagePanel();
        enableInput(true);
        currentStage = "chat";
        loadState();
    });
}

function onAutoEmailToggle() {
    var enabled = document.getElementById("auto-email-toggle").checked;
    var config = document.getElementById("auto-email-config");
    if (enabled) {
        config.classList.remove("hidden");
    } else {
        config.classList.add("hidden");
    }
    var to = document.getElementById("auto-email-to").value || "";
    api("/api/auto-email", { enabled: enabled, to: to.trim() });
}

function toggleSidebar() {
    document.getElementById("sidebar").classList.toggle("open");
}

// ══════════════════════════════════════════════════
// Data Table builders
// ══════════════════════════════════════════════════
function buildDataTable(columns, rows) {
    var html = '<div class="data-table-wrapper"><table class="data-table"><tr>';
    for (var c = 0; c < columns.length; c++) html += '<th>' + columns[c] + '</th>';
    html += '</tr>';
    for (var r = 0; r < rows.length; r++) {
        html += '<tr>';
        var row = rows[r];
        if (Array.isArray(row)) {
            for (var ci = 0; ci < row.length; ci++) html += '<td>' + (row[ci] != null ? row[ci] : '') + '</td>';
        } else {
            for (var ci2 = 0; ci2 < columns.length; ci2++) html += '<td>' + (row[columns[ci2]] != null ? row[columns[ci2]] : '') + '</td>';
        }
        html += '</tr>';
    }
    html += '</table></div>';
    return html;
}

function buildDataTableFromDicts(columns, rows) {
    if (rows.length === 0) return '<div class="info-banner">No data.</div>';
    var dictKeys = Object.keys(rows[0]);
    var html = '<div class="data-table-wrapper"><table class="data-table"><tr>';
    for (var c = 0; c < columns.length; c++) html += '<th>' + columns[c] + '</th>';
    html += '</tr>';
    var max = Math.min(rows.length, 100);
    for (var r = 0; r < max; r++) {
        html += '<tr>';
        for (var ci = 0; ci < columns.length; ci++) {
            var key = dictKeys[ci] || columns[ci];
            html += '<td>' + (rows[r][key] != null ? rows[r][key] : '') + '</td>';
        }
        html += '</tr>';
    }
    html += '</table></div>';
    if (rows.length > 100) {
        html += '<p class="text-sm text-muted mt-2">Showing first 100 of ' + rows.length + ' rows. Download CSV for full data.</p>';
    }
    return html;
}

// ══════════════════════════════════════════════════
// CSV Download
// ══════════════════════════════════════════════════
function downloadSearchCSV() {
    var rows = stageContext.csvRows || [];
    var columns = stageContext.csvColumns || [];
    var csv = columns.join(",") + "\n";
    for (var r = 0; r < rows.length; r++) {
        var row = rows[r];
        if (Array.isArray(row)) {
            csv += row.map(function(c) { return '"' + String(c != null ? c : '').replace(/"/g, '""') + '"'; }).join(",") + "\n";
        } else {
            csv += columns.map(function(c) { return '"' + String(row[c] != null ? row[c] : '').replace(/"/g, '""') + '"'; }).join(",") + "\n";
        }
    }
    downloadBlob(csv, "search_results.csv", "text/csv");
}

function downloadCustomerCSV() {
    var rows = stageContext.csvDictRows || [];
    var cols = stageContext.csvDictColumns || [];
    if (rows.length === 0) return;
    var dictKeys = Object.keys(rows[0]);
    var csv = cols.join(",") + "\n";
    for (var r = 0; r < rows.length; r++) {
        csv += cols.map(function(c, i) {
            var key = dictKeys[i] || c;
            return '"' + String(rows[r][key] != null ? rows[r][key] : '').replace(/"/g, '""') + '"';
        }).join(",") + "\n";
    }
    downloadBlob(csv, "order_details.csv", "text/csv");
}

function downloadBlob(content, filename, type) {
    var blob = new Blob([content], { type: type });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ══════════════════════════════════════════════════
// Collapsible toggle
// ══════════════════════════════════════════════════
function toggleCollapsible(header) {
    var body = header.nextElementSibling;
    if (body.classList.contains("open")) {
        body.classList.remove("open");
        header.textContent = header.textContent.replace("▼", "▶");
    } else {
        body.classList.add("open");
        header.textContent = header.textContent.replace("▶", "▼");
    }
}

// ══════════════════════════════════════════════════
// Loading indicator
// ══════════════════════════════════════════════════
function showLoading() {
    var existing = document.getElementById("loading-msg");
    if (existing) existing.remove();
    var div = document.createElement("div");
    div.id = "loading-msg";
    div.className = "loading-indicator";
    div.innerHTML = '<span class="spinner"></span> Thinking...';
    chatMessages.appendChild(div);
    scrollToBottom();
}

function hideLoading() {
    var el = document.getElementById("loading-msg");
    if (el) el.remove();
}

// ══════════════════════════════════════════════════
// UI state helpers
// ══════════════════════════════════════════════════
function enableInput(enabled) {
    chatInput.disabled = !enabled;
    document.getElementById("btn-send").disabled = !enabled;
    if (enabled) chatInput.focus();
}

function hideStagePanel() {
    stagePanel.classList.add("hidden");
    stagePanel.innerHTML = "";
}

function escapeHtml(text) {
    var div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}
