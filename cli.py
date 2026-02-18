# cli.py
import click
from app.db import Base, engine, SessionLocal
from model.models import EnergySite, EnergySource, Meter


@click.group()
def cli():
    pass


@cli.command()
def init_db():
    Base.metadata.create_all(engine)
    db = SessionLocal()

    factory = EnergySite(name="Energy Factory", type="ENERGY_FACTORY")
    dest = EnergySite(name="Destination Factory", type="DEST_FACTORY")

    bess = EnergySource(name="BESS", cost_per_kwh=0.12)
    solar = EnergySource(name="SOLAR", cost_per_kwh=0.05)

    db.add_all([factory, dest, bess, solar])
    db.commit()

    meters = [
        Meter(serial_number="BESS_01", site_id=factory.id, source_id=bess.id, role="SOURCE"),
        Meter(serial_number="SOLAR_01", site_id=factory.id, source_id=solar.id, role="SOURCE"),
        Meter(serial_number="SELF_01", site_id=factory.id, role="SELF_USE"),
        Meter(serial_number="GRID_01", site_id=factory.id, role="GRID_POINT"),
        Meter(serial_number="DEST_01", site_id=dest.id, role="INTERCONNECT"),
    ]

    db.add_all(meters)
    db.commit()
    db.close()

    print("Database initialized.")


if __name__ == "__main__":
    cli()
