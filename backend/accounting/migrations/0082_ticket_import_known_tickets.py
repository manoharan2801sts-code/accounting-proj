from django.db import migrations

# Airline ticket Auto Push - direct Reschedule / Cancellation (see 0081).
# A Reschedule / Cancellation is saved "direct" only when its ticket was never
# in this software. A ticket that IS here but is no longer live (already
# rescheduled / cancelled) must still be refused - this tells the two apart.
#   dbo.sp_TicketImport_KnownTickets - every Ticket No. of @TicketNosJson found
#   on a Booking, Reschedule or Cancellation of the company (any state).
# Mirrored in StoredProcedures.sql.

PROC_SQL = """
CREATE OR ALTER PROCEDURE dbo.sp_TicketImport_KnownTickets
    @CompanyId      INT,
    @TicketNosJson  NVARCHAR(MAX)            -- ["6E123", ...]
AS
BEGIN
    SET NOCOUNT ON;
    SELECT n.ticket_no,
           CASE WHEN EXISTS (SELECT 1 FROM dbo.Cancellation_Al_TicketLines cl
                             INNER JOIN dbo.Cancellation_AL_Tickets c ON c.id = cl.cancellation_ticket_id
                             WHERE c.company_id = @CompanyId AND cl.ticket_no = n.ticket_no) THEN 'Cancellation'
                WHEN EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_TicketLines rl
                             INNER JOIN dbo.Rescheduled_Al_Ticket r ON r.id = rl.reschedule_ticket_id
                             WHERE r.company_id = @CompanyId AND rl.ticket_no = n.ticket_no) THEN 'Reschedule'
                ELSE 'Booking' END AS found_on
    FROM (SELECT DISTINCT CAST([value] AS NVARCHAR(30)) AS ticket_no FROM OPENJSON(@TicketNosJson)) n
    WHERE EXISTS (SELECT 1 FROM dbo.AL_TicketLines tl INNER JOIN dbo.AL_Tickets t ON t.id = tl.ticket_id
                  WHERE t.company_id = @CompanyId AND tl.ticket_no = n.ticket_no)
       OR EXISTS (SELECT 1 FROM dbo.Rescheduled_Al_TicketLines rl INNER JOIN dbo.Rescheduled_Al_Ticket r ON r.id = rl.reschedule_ticket_id
                  WHERE r.company_id = @CompanyId AND rl.ticket_no = n.ticket_no)
       OR EXISTS (SELECT 1 FROM dbo.Cancellation_Al_TicketLines cl INNER JOIN dbo.Cancellation_AL_Tickets c ON c.id = cl.cancellation_ticket_id
                  WHERE c.company_id = @CompanyId AND cl.ticket_no = n.ticket_no);
END
"""


class Migration(migrations.Migration):

    dependencies = [
        ("accounting", "0081_direct_reschedule_cancellation"),
    ]

    operations = [
        migrations.RunSQL(PROC_SQL, "DROP PROCEDURE IF EXISTS dbo.sp_TicketImport_KnownTickets;"),
    ]
