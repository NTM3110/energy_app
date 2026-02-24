# cli.py
import click
from app.db import Base, engine, SessionLocal
from model.models import EnergySite, EnergySource, Meter


@click.group()
def cli():
    pass

@cli.command(name="init_db")
def init_db():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()

    from model.models import User
    default_user = db.query(User).filter_by(id=1).first()
    if not default_user:
        default_user = User(name="admin", password_hash="hash")
        db.add(default_user)
        db.commit()

    factory = EnergySite(name="Energy Factory", type="ENERGY_FACTORY")
    dest = EnergySite(name="Destination Factory", type="DEST_FACTORY")

    bess = EnergySource(name="BESS", cost_per_kwh=0.12)
    rts = EnergySource(name="RTS", cost_per_kwh=0.05)

    db.add_all([factory, dest, bess, rts])
    db.commit()

    meters = [
        Meter(serial_number=253319561, role="SOURCE",       source_id=bess.id, username="EDMI", password="IMDEIMDE", meter_name="BESS_01", outstation=12, type="EDMI", model="Mk6E", owner_id=default_user.id, site_id=factory.id),
        Meter(serial_number=253319562, role="SOURCE",       source_id=bess.id, username="EDMI", password="IMDEIMDE", meter_name="BESS_02", outstation=12, type="EDMI", model="Mk6E", owner_id=default_user.id, site_id=factory.id),
        Meter(serial_number=253319563, role="SOURCE",       source_id=bess.id, username="EDMI", password="IMDEIMDE", meter_name="BESS_03", outstation=12, type="EDMI", model="Mk6E", owner_id=default_user.id, site_id=factory.id),
        Meter(serial_number=253319564, role="SOURCE",       source_id=bess.id, username="EDMI", password="IMDEIMDE", meter_name="BESS_04", outstation=12, type="EDMI", model="Mk6E", owner_id=default_user.id, site_id=factory.id),
        Meter(serial_number=253319565, role="SOURCE",       source_id=rts.id,  username="EDMI", password="IMDEIMDE", meter_name="RTS_01", outstation=12, type="EDMI", model="Mk6E", owner_id=default_user.id, site_id=factory.id),
        Meter(serial_number=253319566, role="SOURCE",       source_id=rts.id,  username="EDMI", password="IMDEIMDE", meter_name="RTS_02", outstation=12, type="EDMI", model="Mk6E", owner_id=default_user.id, site_id=factory.id),
        Meter(serial_number=253319567, role="SOURCE",       source_id=rts.id,  username="EDMI", password="IMDEIMDE", meter_name="RTS_03", outstation=12, type="EDMI", model="Mk6E", owner_id=default_user.id, site_id=factory.id),
        Meter(serial_number=253319568, role="SOURCE",       source_id=rts.id,  username="EDMI", password="IMDEIMDE", meter_name="RTS_04", outstation=12, type="EDMI", model="Mk6E", owner_id=default_user.id, site_id=factory.id),
        Meter(serial_number=253319569, role="SELF_USE",     source_id=None,    username="EDMI", password="IMDEIMDE", meter_name="SELF_01", outstation=12, type="EDMI", model="Mk6E", owner_id=default_user.id, site_id=factory.id),
        Meter(serial_number=253319570, role="GRID_POINT",   source_id=None,    username="EDMI", password="IMDEIMDE", meter_name="GRID_01", outstation=12, type="EDMI", model="Mk6E", owner_id=default_user.id, site_id=factory.id),
        Meter(serial_number=253319571, role="INTERCONNECT", source_id=None,    username="EDMI", password="IMDEIMDE", meter_name="DEST_01", outstation=12, type="EDMI", model="Mk6E", owner_id=default_user.id, site_id=dest.id),
    ]

    db.add_all(meters)
    db.commit()
    db.close()

    print("Database initialized.")


if __name__ == "__main__":
    cli()
