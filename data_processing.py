#!/project/.venv

# Import relavent packages
import geopandas as gpd
from pathlib import Path
from pyogrio import errors as pyg_err
from pyproj.crs import CRS
import logging
import pandas as pd
import numpy as np

class MisMatchCrs(Exception):
    """This method will be raised if two features do not have matching coordinate systems."""
    pass

class JacksonDataProcessing:
    """The purpose of this class is to perform quality control, assurance, and data processing for project Jackson, MS
    2022 water crisis project. This script could be repurposed for similar analysis involving different cities"""
    def __init__(self, geopackage_location:str, city_boundary_or_mask:str | gpd.GeoDataFrame, mask_layer_name=None, epsg=6509):
        self.geopackage = geopackage_location
        self.mask_layer_name = mask_layer_name
        self.crs = epsg
        self.mask = city_boundary_or_mask

    @property
    def geopackage(self):
        return self._geopackage

    @geopackage.setter
    def geopackage(self, x:str):
        x = Path(x)
        if x.suffix.lower() == ".gpkg":
            self._geopackage = x
        else:
            raise ValueError("The value for geopackage_location must be a geopackage file.")

    @property
    def mask(self):
        return self._mask
    @mask.setter
    def mask(self, x) -> gpd.GeoDataFrame | gpd.GeoSeries:
        """This method creates a mask that will constrain some imported geometries. This is needed for large geospatial
        files with many geometries"""
        try:
            if type(x) is str:
                if self.mask_layer_name is None:
                    mask_gdf = gpd.read_file(Path(x))
                else:
                    mask_gdf = gpd.read_file(Path(x), layer=self.mask_layer_name)

                # Maybe check if geoseries/geodataframe is only points

                x = mask_gdf
            elif (type(x) is gpd.GeoDataFrame) or (type(x) is gpd.GeoSeries):
                pass
            else:
                raise ValueError(f"Mask must be type {gpd.GeoDataFrame}, {gpd.GeoSeries}, or {Path}. Not {type(x)}")
            if x.crs.to_epsg() != self.crs.to_epsg():
                self._mask = x.to_crs(self.crs)
            else:
                self._mask = x

        except pyg_err.DataSourceError:
            raise ValueError("The file provided was not recognized by geopandas. Try converting the file to a different vector filetype such as .shp")

    @property
    def crs(self) -> CRS:
        return self._crs

    @crs.setter
    def crs(self, x):
        """This method converts the EPSG code provided to the object into a pyproj.CRS object and performs relavent checks."""
        crs_object = CRS(x)
        if crs_object.is_projected:
            self._crs = CRS(x)
        else:
            raise ValueError("The projection provided must be projected coordinate system")


    def _check_same_crs(self, feature_1:gpd.GeoDataFrame | gpd.GeoSeries, feature_2:gpd.GeoDataFrame | gpd.GeoSeries):
        """This method performs QA by checking that coordinate systems are the same before performing calculations"""
        if feature_1.crs == feature_2.crs:
            return True
        else:
            return False

    def _feature_checks(self, feature:Path, layername=None, mask = True) -> gpd.GeoDataFrame | gpd.GeoSeries:
        """This method will be used whenever the user inputs a geospatial file. It will perform common checks."""
        if mask is True:
            if layername is None:
                feature_gdf = gpd.read_file(feature, mask=self.mask)
            else:
                feature_gdf = gpd.read_file(feature, layer=layername, mask=self.mask)

        elif mask is False:
            if layername is None:
                feature_gdf = gpd.read_file(feature)
            else:
                feature_gdf = gpd.read_file(feature, layer=layername)
        else:
            raise ValueError()

        if feature_gdf.crs.to_epsg() != self.crs.to_epsg():
            logging.info(
                f"The building footprints data was projected in {feature_gdf.crs}. Converting to object's CRS.")
            feature_gdf = feature_gdf.to_crs(self.crs)
        return feature_gdf


    def _check_if_pcrs(self, feature:gpd.GeoDataFrame | gpd.GeoSeries):
        """This method performs QC by ensuring coordinate system is a projected coordinate system before performing
        analysis."""
        if feature.crs.is_projected:
            return True
        else:
            return False

    def mask_buildings(self, building_footprints) -> gpd.GeoDataFrame:
        """Masks building footprint polygons and reprojects data."""
        print("Reading and reprojecting json file of building footprints.")
        building_footprint_gdf = self._feature_checks(building_footprints)
        return building_footprint_gdf



    def mask_roads(self, roads_path, layer_name = None):
        """Masks road linear features and reprojects data."""
        roads_gdf = self._feature_checks(roads_path, layer_name)
        return roads_gdf

    def mask_zip(self, zipcodes, layer_name = None):
        """Masks zip code polygons and reprojects data."""
        zipcode_gdf = self._feature_checks(zipcodes, layer_name)
        return zipcode_gdf

    def water_distribution_by_tiger_zip_per_capital(self, zipcodes_shp, zipcode_relationship_file_csv, water_distribution_file_location, water_distribution_layer_name):
        """This method uses Census Tiger files and relational zipcode data to calculate the number of distribution
        centers in a zip code per 10,000 people."""
        # Create geodataframe for zip codes. Mask the codes to the Jackson, MS city boundary
        zipcode_gdf = self._feature_checks(zipcodes_shp)
        # Create geodataframe for water distribution sites. Mask is turned off because some points are within zip codes
        # masked by the city, but do not intersect city boundary polygon.
        water_distribution_center_gdf = self._feature_checks(water_distribution_file_location, water_distribution_layer_name, mask=False)
        # First row is skipped because it provides metadata.
        zipcode_relationship_file = pd.read_csv(zipcode_relationship_file_csv, skiprows=1)
        # A right spatial join is performed to get the number combine zip code data with water distribution sites.
        # This shows the number of "hits" a zipcode has based on the number of intersecting water distribution sites.
        water_distribution_per_zip = gpd.sjoin(zipcode_gdf, water_distribution_center_gdf, how="right")
        # Count column is created to ensure there is a column that can be used to count the number of times a zip code occurs.
        water_distribution_per_zip["count"] = 1
        # Data us griyoed by GEOIDFQ20 because this field is the key for joining demographic data aggregated to zip codes.
        water_distribution_per_zip = water_distribution_per_zip.groupby("GEOIDFQ20").count()["count"].reset_index()
        # Performs an outer join of distribution sites and aggregated demographic data. I used an outer join because I do not want to potentially lose data, although, left join should work.
        water_dist_per_capita = pd.merge(water_distribution_per_zip, zipcode_relationship_file, left_on="GEOIDFQ20", right_on="Geography", how="outer").reset_index()
        # Creates a new column and divides the count of water distribution centers by the total population for the zip code.
        # This normalizes the data to give centers per capita, which is multiplied by 10,000 to get the number of centers per 10,000 people.
        water_dist_per_capita.loc[:, "Per_10000_ppl"] = water_dist_per_capita["count"]/water_dist_per_capita[" !!Total"] * 10_000

        # Fill NA with 0 since NA indicates no water distribution sites in that zipcode.
        water_dist_per_capita.loc[:, "Per_10000_ppl"] = water_dist_per_capita.loc[:, "Per_10000_ppl"].fillna(0)
        # N/A is given to inf values because inf values represent zip codes that have a population of 0.
        water_dist_per_capita.loc[:, "Per_10000_ppl"] = water_dist_per_capita.loc[:, "Per_10000_ppl"].replace([np.inf, -np.inf], np.nan)
        return pd.merge(zipcode_gdf[["ZCTA5CE20", "GEOIDFQ20", "geometry"]], water_dist_per_capita, left_on="GEOIDFQ20", right_on="Geography", how="left") # Need to group by zipcode

    def clip_gdf_to_city(self, gdf):
        """This method performs a clip to cut point, line, and polygon features based on the class's mask."""
        return gdf.clip(self.mask)
