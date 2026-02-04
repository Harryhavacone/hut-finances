"""
Holiday House Expense Splitter - Streamlit App (Cloud Version)
Uses Google Sheets for persistent storage.
"""

import csv
import io
import streamlit as st
from collections import defaultdict
import gspread
from google.oauth2.service_account import Credentials

# Google Sheets setup
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


@st.cache_resource
def get_gspread_client():
    """Get authenticated gspread client."""
    credentials = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"],
        scopes=SCOPES,
    )
    return gspread.authorize(credentials)


def get_worksheet():
    """Get the worksheet for storing data."""
    client = get_gspread_client()
    sheet_url = st.secrets["spreadsheet_url"]
    spreadsheet = client.open_by_url(sheet_url)
    return spreadsheet.sheet1


def load_saved_data() -> dict:
    """Load saved data from Google Sheets."""
    try:
        worksheet = get_worksheet()
        # Data stored in cells: A1=families, A2=stays, A3=expenses
        values = worksheet.get("A1:A3")
        if values and len(values) >= 3:
            return {
                'families': values[0][0] if values[0] else "",
                'stays': values[1][0] if values[1] else "",
                'expenses': values[2][0] if values[2] else "",
            }
    except Exception as e:
        st.warning(f"Could not load data from Google Sheets: {e}")
    return {}


def save_data(families: str, stays: str, expenses: str):
    """Save data to Google Sheets."""
    try:
        worksheet = get_worksheet()
        # Store each data type in a separate row
        worksheet.update("A1:A3", [[families], [stays], [expenses]])
    except Exception as e:
        st.error(f"Could not save data to Google Sheets: {e}")


def parse_families(text: str) -> dict[str, str]:
    """Parse families data and return member_name -> family_name mapping.
    Format: FamilyName:Member1,Member2,Member3
    """
    member_to_family = {}
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or ':' not in line:
            continue
        family_name, members_str = line.split(':', 1)
        family_name = family_name.strip()
        for member in members_str.split(','):
            member = member.strip()
            if member:
                member_to_family[member] = family_name
    return member_to_family


def parse_stays(text: str) -> list[dict]:
    """Parse stays data and return list of stay records.
    Format: MemberName,Nights (one per line)
    """
    stays = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or ',' not in line:
            continue
        parts = line.split(',')
        if len(parts) >= 2:
            member = parts[0].strip()
            try:
                nights = int(parts[1].strip())
                stays.append({'member_name': member, 'nights': nights})
            except ValueError:
                continue
    return stays


def parse_expenses(text: str) -> list[dict]:
    """Parse expenses data and return list of expense records.
    Format: Family,Type,Amount,Description (one per line)
    """
    expenses = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line or ',' not in line:
            continue
        parts = line.split(',')
        if len(parts) >= 3:
            try:
                expenses.append({
                    'paid_by_family': parts[0].strip(),
                    'expense_type': parts[1].strip(),
                    'amount': float(parts[2].strip()),
                    'description': parts[3].strip() if len(parts) > 3 else '',
                })
            except ValueError:
                continue
    return expenses


def calculate_person_nights(stays: list[dict], member_to_family: dict[str, str]) -> dict[str, int]:
    """Calculate total person-nights per family."""
    family_nights = defaultdict(int)
    for stay in stays:
        member = stay['member_name']
        nights = stay['nights']
        family = member_to_family[member]
        family_nights[family] += nights
    return dict(family_nights)


def calculate_family_payments(expenses: list[dict]) -> dict[str, float]:
    """Calculate total amount paid by each family."""
    payments = defaultdict(float)
    for expense in expenses:
        payments[expense['paid_by_family']] += expense['amount']
    return dict(payments)


def calculate_expense_totals_by_type(expenses: list[dict]) -> dict[str, float]:
    """Calculate total expenses by type."""
    totals = defaultdict(float)
    for expense in expenses:
        totals[expense['expense_type']] += expense['amount']
    return dict(totals)


def calculate_settlements(balances: dict[str, float]) -> list[tuple[str, str, float]]:
    """Calculate minimal settlements using greedy matching."""
    debtors = []
    creditors = []

    for family, balance in balances.items():
        if balance < -0.01:
            debtors.append([family, -balance])
        elif balance > 0.01:
            creditors.append([family, balance])

    debtors.sort(key=lambda x: (-x[1], x[0]))
    creditors.sort(key=lambda x: (-x[1], x[0]))

    settlements = []

    while debtors and creditors:
        debtor, debt = debtors[0]
        creditor, credit = creditors[0]

        amount = min(debt, credit)
        if amount > 0.01:
            settlements.append((debtor, creditor, amount))

        debtors[0][1] -= amount
        creditors[0][1] -= amount

        if debtors[0][1] < 0.01:
            debtors.pop(0)
        if creditors[0][1] < 0.01:
            creditors.pop(0)

    return settlements


def generate_report(member_to_family, stays, expenses, family_nights, family_payments, total_expenses, balances, settlements):
    """Generate text report."""
    lines = []

    lines.append("=" * 50)
    lines.append("EXPENSE SUMMARY")
    lines.append("=" * 50)

    totals_by_type = calculate_expense_totals_by_type(expenses)
    for expense_type, amount in sorted(totals_by_type.items()):
        lines.append(f"  {expense_type.capitalize():20} €{amount:>10.2f}")

    lines.append("-" * 50)
    lines.append(f"  {'TOTAL':20} €{total_expenses:>10.2f}")
    lines.append("")

    lines.append("=" * 50)
    lines.append("EXPENSE DETAILS (by Family)")
    lines.append("=" * 50)

    # Group expenses by family
    family_expenses = defaultdict(list)
    for expense in expenses:
        family_expenses[expense['paid_by_family']].append(expense)

    for family in sorted(family_expenses.keys()):
        lines.append(f"\n  {family} Family:")
        family_total = 0
        for exp in family_expenses[family]:
            desc = f" - {exp['description']}" if exp['description'] else ""
            lines.append(f"    {exp['expense_type']:15} €{exp['amount']:>10.2f}{desc}")
            family_total += exp['amount']
        lines.append(f"    {'Subtotal':15} €{family_total:>10.2f}")

    lines.append("")

    lines.append("=" * 50)
    lines.append("STAY SUMMARY (Person-Nights)")
    lines.append("=" * 50)

    family_stays = defaultdict(list)
    for stay in stays:
        member = stay['member_name']
        family = member_to_family[member]
        nights = stay['nights']
        family_stays[family].append((member, nights))

    total_nights = 0
    for family in sorted(family_stays.keys()):
        lines.append(f"\n  {family} Family:")
        family_total = 0
        for member, nights in sorted(family_stays[family]):
            lines.append(f"    {member:15} {nights:3} nights")
            family_total += nights
        lines.append(f"    {'Subtotal':15} {family_total:3} nights")
        total_nights += family_total

    lines.append("-" * 50)
    lines.append(f"  TOTAL PERSON-NIGHTS: {total_nights}")
    lines.append("")

    lines.append("=" * 50)
    lines.append("BALANCE SHEET")
    lines.append("=" * 50)

    cost_per_night = total_expenses / total_nights
    lines.append(f"\n  Cost per person-night: €{cost_per_night:.2f}")
    lines.append("")
    lines.append(f"  {'Family':<10} {'Nights':>8} {'Owes':>12} {'Paid':>12} {'Balance':>12}")
    lines.append("  " + "-" * 54)

    all_families = set(family_nights.keys()) | set(family_payments.keys())
    for family in sorted(all_families):
        nights = family_nights.get(family, 0)
        paid = family_payments.get(family, 0)
        owes = nights * cost_per_night
        balance = balances[family]
        balance_str = f"€{balance:>10.2f}" if balance >= 0 else f"-€{abs(balance):>9.2f}"
        lines.append(f"  {family:<10} {nights:>8} €{owes:>10.2f} €{paid:>10.2f} {balance_str}")

    lines.append("")
    lines.append("=" * 50)
    lines.append("SETTLEMENTS")
    lines.append("=" * 50)

    if not settlements:
        lines.append("\n  No settlements needed - all balanced!")
    else:
        lines.append("")
        for payer, payee, amount in settlements:
            lines.append(f"  {payer} pays {payee}: €{amount:.2f}")

    return "\n".join(lines)


def generate_csv_report(member_to_family, stays, expenses, family_nights, family_payments, total_expenses, balances, settlements):
    """Generate CSV report with multiple sections."""
    output = io.StringIO()

    # Balance Sheet section
    output.write("BALANCE SHEET\n")
    writer = csv.writer(output)
    writer.writerow(["Family", "Nights", "Owes", "Paid", "Balance"])

    total_nights = sum(family_nights.values())
    cost_per_night = total_expenses / total_nights
    all_families = set(family_nights.keys()) | set(family_payments.keys())

    for family in sorted(all_families):
        nights = family_nights.get(family, 0)
        paid = family_payments.get(family, 0)
        owes = nights * cost_per_night
        balance = balances[family]
        writer.writerow([family, nights, f"{owes:.2f}", f"{paid:.2f}", f"{balance:.2f}"])

    output.write("\n")

    # Settlements section
    output.write("SETTLEMENTS\n")
    writer.writerow(["From", "To", "Amount"])
    if settlements:
        for payer, payee, amount in settlements:
            writer.writerow([payer, payee, f"{amount:.2f}"])
    else:
        writer.writerow(["No settlements needed"])

    output.write("\n")

    # Expense Details section
    output.write("EXPENSE DETAILS\n")
    writer.writerow(["Family", "Type", "Amount", "Description"])
    for expense in sorted(expenses, key=lambda x: x['paid_by_family']):
        writer.writerow([
            expense['paid_by_family'],
            expense['expense_type'],
            f"{expense['amount']:.2f}",
            expense['description']
        ])

    output.write("\n")

    # Stay Details section
    output.write("STAY DETAILS\n")
    writer.writerow(["Family", "Member", "Nights"])
    stays_with_family = [(member_to_family[s['member_name']], s['member_name'], s['nights']) for s in stays]
    for family, member, nights in sorted(stays_with_family):
        writer.writerow([family, member, nights])

    return output.getvalue()


# Streamlit App
st.set_page_config(page_title="Holiday House Expense Splitter", page_icon="🏠")

st.title("🏠 Holiday House Expense Splitter")
st.write("Calculate fair expense splits based on person-nights stayed.")

# Load saved data or use defaults
saved = load_saved_data()
default_families = saved.get('families', "Adams:John,Mary,Tom\nOiler:Bob,Sue\nBaker:Ann")
default_stays = saved.get('stays', "John,7\nMary,5\nTom,5\nBob,7\nSue,3\nAnn,7")
default_expenses = saved.get('expenses', "Adams,rent,2100,House rental\nOiler,firewood,150,Firewood\nBaker,food,320,Groceries")

col1, col2 = st.columns(2)

with col1:
    st.write("**Families** (Family:Member1,Member2,...)")
    families_data = st.text_area(
        "Families",
        value=default_families,
        height=120,
        label_visibility="collapsed"
    )

    st.write("**Stays** (Member,Nights)")
    stays_data = st.text_area(
        "Stays",
        value=default_stays,
        height=150,
        label_visibility="collapsed"
    )

with col2:
    st.write("**Expenses** (Family,Type,Amount,Description)")
    expenses_data = st.text_area(
        "Expenses",
        value=default_expenses,
        height=285,
        label_visibility="collapsed"
    )

# Save button
st.divider()
col_save, col_calc = st.columns(2)

with col_save:
    if st.button("💾 Save Data", type="secondary"):
        save_data(families_data, stays_data, expenses_data)
        st.success("Data saved to Google Sheets!")

with col_calc:
    calculate_clicked = st.button("Calculate", type="primary")

if calculate_clicked:
    if families_data and stays_data and expenses_data:
        try:
            member_to_family = parse_families(families_data)
            stays = parse_stays(stays_data)
            expenses = parse_expenses(expenses_data)

            # Validate members in stays
            known_members = set(member_to_family.keys())
            unknown_members = []
            for stay in stays:
                if stay['member_name'] not in known_members:
                    unknown_members.append(stay['member_name'])

            if unknown_members:
                st.error(f"Unknown member(s) in Stays: {', '.join(unknown_members)}")
                st.write("Please add these members to the Families data.")
                if 'results' in st.session_state:
                    del st.session_state['results']
                st.stop()

            # Validate families in expenses
            known_families = set(member_to_family.values())
            unknown_families = []
            for expense in expenses:
                if expense['paid_by_family'] not in known_families:
                    unknown_families.append(expense['paid_by_family'])

            if unknown_families:
                st.error(f"Unknown family/families in Expenses: {', '.join(set(unknown_families))}")
                st.write("Please add these families to the Families data.")
                if 'results' in st.session_state:
                    del st.session_state['results']
                st.stop()

            family_nights = calculate_person_nights(stays, member_to_family)
            family_payments = calculate_family_payments(expenses)
            total_expenses = sum(e['amount'] for e in expenses)
            total_nights = sum(family_nights.values())
            cost_per_night = total_expenses / total_nights

            balances = {}
            all_families = set(family_nights.keys()) | set(family_payments.keys())
            for family in all_families:
                nights = family_nights.get(family, 0)
                paid = family_payments.get(family, 0)
                owes = nights * cost_per_night
                balances[family] = paid - owes

            settlements = calculate_settlements(balances)

            # Store results in session state
            st.session_state['results'] = {
                'member_to_family': member_to_family,
                'stays': stays,
                'expenses': expenses,
                'family_nights': family_nights,
                'family_payments': family_payments,
                'total_expenses': total_expenses,
                'total_nights': total_nights,
                'cost_per_night': cost_per_night,
                'balances': balances,
                'settlements': settlements,
                'all_families': all_families,
            }
        except Exception as e:
            st.error(f"Error processing data: {e}")
            st.write("Please check your data format and try again.")
            if 'results' in st.session_state:
                del st.session_state['results']

# Display results if available
if 'results' in st.session_state:
    r = st.session_state['results']
    member_to_family = r['member_to_family']
    stays = r['stays']
    expenses = r['expenses']
    family_nights = r['family_nights']
    family_payments = r['family_payments']
    total_expenses = r['total_expenses']
    total_nights = r['total_nights']
    cost_per_night = r['cost_per_night']
    balances = r['balances']
    settlements = r['settlements']
    all_families = r['all_families']

    st.divider()

    # Summary metrics
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Expenses", f"€{total_expenses:,.2f}")
    col2.metric("Total Person-Nights", total_nights)
    col3.metric("Cost per Night", f"€{cost_per_night:,.2f}")

    st.divider()

    # Settlements - the most important part
    st.subheader("💸 Settlements")
    if settlements:
        for payer, payee, amount in settlements:
            st.info(f"**{payer}** pays **{payee}**: **€{amount:,.2f}**")
    else:
        st.success("No settlements needed - all balanced!")

    st.divider()

    # Detailed breakdown in expanders
    with st.expander("📊 Balance Sheet"):
        balance_data = []
        for family in sorted(all_families):
            nights = family_nights.get(family, 0)
            paid = family_payments.get(family, 0)
            owes = nights * cost_per_night
            balance = balances[family]
            balance_data.append({
                "Family": family,
                "Nights": nights,
                "Owes": f"€{owes:,.2f}",
                "Paid": f"€{paid:,.2f}",
                "Balance": f"€{balance:,.2f}" if balance >= 0 else f"-€{abs(balance):,.2f}"
            })
        st.table(balance_data)

    with st.expander("🛏️ Stays by Family"):
        family_stays = defaultdict(list)
        for stay in stays:
            member = stay['member_name']
            family = member_to_family[member]
            family_stays[family].append((member, stay['nights']))

        for family in sorted(family_stays.keys()):
            st.write(f"**{family} Family**")
            for member, nights in sorted(family_stays[family]):
                st.write(f"  - {member}: {nights} nights")
            st.write(f"  - *Subtotal: {sum(n for _, n in family_stays[family])} nights*")

    with st.expander("💰 Expenses by Category"):
        totals_by_type = calculate_expense_totals_by_type(expenses)
        for expense_type, amount in sorted(totals_by_type.items()):
            st.write(f"- {expense_type.capitalize()}: €{amount:,.2f}")

    # Download reports
    st.divider()
    report = generate_report(member_to_family, stays, expenses, family_nights,
                             family_payments, total_expenses, balances, settlements)
    csv_report = generate_csv_report(member_to_family, stays, expenses, family_nights,
                                     family_payments, total_expenses, balances, settlements)

    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "📥 Download Report (TXT)",
            report,
            file_name="expense_report.txt",
            mime="text/plain"
        )
    with col2:
        st.download_button(
            "📥 Download Report (CSV)",
            csv_report,
            file_name="expense_report.csv",
            mime="text/csv"
        )
