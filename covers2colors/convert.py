import colorsys, json, os, pkg_resources
from urllib.error import HTTPError
from urllib.error import URLError
from urllib.request import urlopen
import matplotlib.pyplot as plt
import matplotlib as mpl
from mpl_toolkits.axes_grid1 import make_axes_locatable
import numpy as np
from kneed import KneeLocator
from PIL import Image
from sklearn.cluster import KMeans
from matplotlib.colors import ListedColormap
from sklearn.cluster import MiniBatchKMeans
from .album_art import get_best_cover_art_url
from scipy.spatial.distance import pdist, squareform

class CoverColors:
    """
    A class to convert album artwork to a numpy array of RGB values.

    Args:
        artist (str): The name of the artist.
        album (str): The name of the album.

    Attributes:
        image_path (str): The URL of the cover art image.
        album (str): The name of the album.
        image (PIL.Image): The PIL Image object of the cover art.
        pixels (numpy.ndarray): A numpy array of RGB values representing the cover art.
        transparent_pixels (numpy.ndarray): A boolean numpy array where True indicates the corresponding pixel in the cover art is transparent.
        kmeans (KMeans): The KMeans object after fitting to the RGB values. None if the `fit_kmeans` method has not been called.
        hexcodes (list): The list of hexcodes representing the dominant colors in the cover art. None if the `get_hexcodes` method has not been called.
    """

    def __init__(self, artist, album):
        """
        Initializes the CoverColors object by fetching the cover art and converting it to a numpy array of RGB values.
        """
        api_key = None
        keys_path = pkg_resources.resource_filename('covers2colors', 'keys.json')
        with open(keys_path, 'r') as f:
            config = json.load(f)
            api_key = config['lastfm']['api_key']

        cover_art_url = get_best_cover_art_url(artist, album, api_key = api_key)
        self.image_path = cover_art_url
        self.album = album
        try:
            self.image = Image.open(urlopen(self.image_path))
        except (URLError, HTTPError) as error:
            raise URLError(f"Could not open {self.image_path} {error}") from error
        except ValueError as error:
            raise ValueError(f"Could not open {self.image_path} {error}") from error

        # convert the image to a numpy array
        self.image = self.image.convert("RGBA")
        self.pixels = np.array(self.image.getdata())

        # Find transparent pixels and store them in case we want to remove transparency
        self.transparent_pixels = self.pixels[:, 3] == 0
        self.pixels = self.pixels[:, :3]
        self.kmeans = None
        self.hexcodes = None

    def generate_cmap(self, n_colors=4, palette_name = None, random_state=None):
        """Generates a matplotlib ListedColormap from an image.

        Args:
            n_colors (int, optional): The number of colors in the ListedColormap. Defaults to 4.
            palette_name (str, optional): A name for your created palette. If None, defaults to the image name.
                Defaults to None.
            random_state (int, optional): A random seed for reproducing ListedColormaps.
                The k-means algorithm has a random initialization step and doesn't always converge on the same
                solution because of this. If None will be a different seed each time this method is called.
                Defaults to None.

        Returns:
            matplotlib.colors.ListedColormap: A matplotlib ListedColormap object.
        """
        # create a kmeans model
        self.kmeans = MiniBatchKMeans(n_clusters=n_colors, random_state=random_state, n_init=3)
        # fit the model to the pixels
        self.kmeans.fit(self.pixels)
        # get the cluster centers
        centroids = self.kmeans.cluster_centers_ / 255
        # return the palette
        if not palette_name:
            palette_name = self.album
        cmap = mpl.colors.ListedColormap(centroids, name=palette_name)

        # Handle 4 dimension RGBA colors
        cmap.colors = cmap.colors[:, :3]

        # Sort colors by hue
        cmap.colors = sorted(cmap.colors, key=lambda rgb: colorsys.rgb_to_hsv(*rgb))
        # Handle cases where all rgb values evaluate to 1 or 0. This is a temporary fix
        cmap.colors = np.where(np.isclose(cmap.colors, 1), 1 - 1e-6, cmap.colors)
        cmap.colors = np.where(np.isclose(cmap.colors, 0), 1e-6, cmap.colors)

        self.hexcodes = [mpl.colors.rgb2hex(c) for c in cmap.colors]
        return cmap

    def generate_optimal_cmap(self, max_colors=10, palette_name=None, random_state=None):
        """Generates an optimal matplotlib ListedColormap from an image by finding the optimal number of clusters using the elbow method.

        Useage:
            >>> img = ImageConverter("path/to/image.png")
            >>> cmaps, best_n_colors, ssd = img.generate_optimal_cmap()
            >>> # The optimal colormap
            >>> cmaps[best_n_colors]


        Args:
            max_colors (int, optional): _description_. Defaults to 10.
            palette_name (_type_, optional): _description_. Defaults to None.
            random_state (_type_, optional): _description_. Defaults to None.
            remove_background (_type_, optional): _description_. Defaults to None.

        Returns:
            dict: A dictionary of matplotlib ListedColormap objects.
            Keys are the number of colors (clusters). Values are ListedColormap objects.
            int: The optimal number of colors.
            dict: A dictionary of the sum of square distances from each point to the cluster center.
            Keys are the number of colors (clusters) and values are the SSD value.
        """
        ssd = dict()
        cmaps = dict()
        if not palette_name:
            palette_name = self.album
        for n_colors in range(2, max_colors + 1):
            cmap = self.generate_cmap(n_colors=n_colors, palette_name=palette_name, random_state=random_state)
            cmaps[n_colors] = cmap
            ssd[n_colors] = self.kmeans.inertia_

        best_n_colors = KneeLocator(list(ssd.keys()), list(ssd.values()), curve="convex", direction="decreasing").knee
        try:
            self.hexcodes = [mpl.colors.rgb2hex(c) for c in cmaps[best_n_colors].colors]
        except KeyError:
            # Kneed did not find an optimal point so we don't record any hex values
            self.hexcodes = None
        return cmaps, best_n_colors, ssd
    
    def get_distinct_colors(self, cmap, n_colors):
        """Get the most distinct colors from a colormap.

        Args:
            cmap (matplotlib.colors.ListedColormap): The colormap.
            n_colors (int): The number of distinct colors to get.

        Returns:
            list: A list of the most distinct RGB color tuples.
        """
        # Convert the colormap colors to a 2D array
        colors = np.array(cmap.colors)

        # Use KMeans to find the most distinct colors
        kmeans = KMeans(n_clusters=n_colors, random_state=0, n_init=1).fit(colors)

        # Get the most distinct colors
        distinct_colors = kmeans.cluster_centers_
        distinct_colors = np.array(distinct_colors)

        # Create a colormap from the distinct colors
        distinct_cmap = ListedColormap(distinct_colors)
        
        return distinct_colors, distinct_cmap
    
    def generate_distinct_optimal_cmap(self, max_colors=10, n_distinct_colors=4, palette_name=None, random_state=None):
        """Generates an optimal colormap and then picks the most distinct colors from it.

        Args:
            max_colors (int, optional): The maximum number of colors to consider for the colormap. Defaults to 10.
            n_distinct_colors (int, optional): The number of distinct colors to pick from the optimal colormap. Defaults to 4.
            palette_name (_type_, optional): The name of the palette to use. Defaults to None.
            random_state (_type_, optional): The seed for the random number generator. Defaults to None.

        Returns:
            list: A list of the most distinct RGB color tuples.
            matplotlib.colors.ListedColormap: A colormap of the most distinct colors.
        """
        # Generate the optimal colormap
        cmaps, best_n_colors, ssd = self.generate_optimal_cmap(max_colors, palette_name, random_state)

        max_distinctness = 0
        best_distinct_colors = None
        best_distinct_cmap = None
        # Pick the most distinct colors from the optimal colormap
        for n_colors, cmap in cmaps.items():
            if len(cmap.colors) < n_distinct_colors:
                continue
            
            distinct_colors, distinct_cmap = self.get_distinct_colors(cmap, n_distinct_colors)

            # Calculate the total pairwise distance between the colors
            distinctness = np.sum(squareform(pdist(distinct_colors)))

            # If this set of colors is more distinct than the best so far, update the best
            if distinctness > max_distinctness:
                max_distinctness = distinctness
                best_distinct_colors = distinct_colors
                best_distinct_cmap = distinct_cmap
        
        best_distinct_colors = np.array(best_distinct_colors)

        return best_distinct_colors, best_distinct_cmap

    def remove_transparent(self):
        """Removes the transparent pixels from an image array.

        Returns:
            None
        """
        self.pixels = self.pixels[~self.transparent_pixels]

    def display_with_colorbar(self, cmap):
        """
        Display an image with a colorbar.

        Parameters:
        cmap (matplotlib.colors.Colormap): The colormap to use.

        Returns:
        None
        """
        try:
            # Open the image from the URL
            with urlopen(self.image_path) as url:
                with Image.open(url) as img:
                    img_array = np.array(img)

            # Create the plot
            fig, ax = plt.subplots(figsize=(7, 5))
            ax.axis("off")
            im = ax.imshow(img_array, cmap=cmap)

            # Add a colorbar
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="10%", pad=0.05)
            cb = fig.colorbar(im, cax=cax, orientation="vertical")
            cb.set_ticks([])

            # Display the plot
            plt.show()

        except Exception as e:
            print(f"Error displaying image with colorbar: {e}")
