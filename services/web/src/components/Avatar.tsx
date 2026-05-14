import avatarImage from "@/assets/avatar.jpeg";

const Avatar = () => {
  return (
    <img
      src={avatarImage}
      alt="Artem Vozniuk"
      className="h-36 w-36 sm:h-44 sm:w-44 shrink-0 rounded-2xl border border-border/50 object-cover shadow-elegant"
    />
  );
};

export default Avatar;
